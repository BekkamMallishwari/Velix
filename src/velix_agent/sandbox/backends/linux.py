import contextlib
import fcntl
import hashlib
import os
import platform
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import typing
from pathlib import Path

from velix_agent.core.logging import get_logger
from velix_agent.sandbox.backends.base import SandboxBackend
from velix_agent.sandbox.policy import SandboxCapabilities, SandboxPolicy
from velix_agent.sandbox.result import (
    OUTPUT_TRUNCATION_MARKER,
    SandboxError,
    SandboxResult,
)

logger = get_logger("sandbox.linux")


class LinuxSandboxBackend(SandboxBackend):
    MAX_OUTPUT_BYTES = 50_000

    _systemd_supported_cache: typing.ClassVar[bool | None] = None
    _unshare_net_supported_cache: typing.ClassVar[bool | None] = None
    _bwrap_execution_supported_cache: typing.ClassVar[bool | None] = None

    # Workspace coordination for transient .git sentinel management
    _sentinel_global_lock: typing.ClassVar[threading.Lock] = threading.Lock()
    _workspace_sentinels: typing.ClassVar[dict[str, dict[str, typing.Any]]] = {}

    @classmethod
    def _detect_systemd(cls) -> bool:
        if cls._systemd_supported_cache is None:
            if not shutil.which("systemd-run"):
                cls._systemd_supported_cache = False
            else:
                try:
                    res = subprocess.run(
                        [
                            "systemd-run",
                            "--user",
                            "--scope",
                            "-q",
                            "--no-ask-password",
                            "--property=MemoryMax=100M",
                            "--property=TasksMax=10",
                            "true",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2,
                    )
                    cls._systemd_supported_cache = res.returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    cls._systemd_supported_cache = False
                except Exception:
                    cls._systemd_supported_cache = False
        return bool(cls._systemd_supported_cache)

    @classmethod
    def _detect_unshare_net(cls) -> bool:
        if cls._unshare_net_supported_cache is None:
            if not shutil.which("bwrap"):
                cls._unshare_net_supported_cache = False
            else:
                try:
                    res = subprocess.run(
                        ["bwrap", "--unshare-net", "--bind", "/", "/", "--", "true"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2,
                    )
                    cls._unshare_net_supported_cache = res.returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    cls._unshare_net_supported_cache = False
        return bool(cls._unshare_net_supported_cache)

    @classmethod
    def _detect_bwrap_execution(cls) -> bool:
        if cls._bwrap_execution_supported_cache is None:
            if not shutil.which("bwrap"):
                cls._bwrap_execution_supported_cache = False
            else:
                try:
                    res = subprocess.run(
                        ["bwrap", "--bind", "/", "/", "--", "true"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2,
                    )
                    cls._bwrap_execution_supported_cache = res.returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    cls._bwrap_execution_supported_cache = False
        return bool(cls._bwrap_execution_supported_cache)

    @classmethod
    def is_bwrap_installed(cls) -> bool:
        """Check if the bubblewrap (bwrap) binary is present in PATH."""
        return shutil.which("bwrap") is not None

    @classmethod
    def is_bwrap_execution_supported(cls, require_network_isolation: bool = True) -> bool:
        """Check if bubblewrap can genuinely execute an unprivileged sandbox container.

        Checks unprivileged user namespace execution, and optionally requires network
        namespace isolation (--unshare-net), matching the CI workflow and sandbox execution
        requirements.
        """
        if not cls._detect_bwrap_execution():
            return False
        if require_network_isolation:
            return cls._detect_unshare_net()
        return True

    @classmethod
    def get_capabilities(cls) -> SandboxCapabilities:
        has_bwrap = cls.is_bwrap_execution_supported(require_network_isolation=False)
        if not has_bwrap:
            return SandboxCapabilities(
                filesystem_isolation="NOT_AVAILABLE",
                network_isolation="NOT_AVAILABLE",
                cpu_limit="NOT_AVAILABLE",
                memory_limit="NOT_AVAILABLE",
                process_limit="NOT_AVAILABLE",
                timeout="SUPPORTED",
                output_limit="SUPPORTED",
                secret_filtering="SUPPORTED",
                disk_limit="UNSUPPORTED",
                runtime_isolation="UNSUPPORTED",
                observability="UNSUPPORTED",
                security_hardening="UNSUPPORTED",
            )

        has_cgroups = cls._detect_systemd()
        from velix_agent.sandbox.policy import SupportStatus

        limit_status: SupportStatus = "SUPPORTED" if has_cgroups else "PARTIALLY_SUPPORTED"
        net_status: SupportStatus = "SUPPORTED" if cls._detect_unshare_net() else "UNSUPPORTED"

        return SandboxCapabilities(
            filesystem_isolation="SUPPORTED",
            network_isolation=net_status,
            cpu_limit="PARTIALLY_SUPPORTED",  # Enforced via per-process setrlimit
            memory_limit=limit_status,
            process_limit=limit_status,
            timeout="SUPPORTED",
            output_limit="SUPPORTED",
            secret_filtering="SUPPORTED",
            disk_limit="UNSUPPORTED",
            runtime_isolation="UNSUPPORTED",
            observability="UNSUPPORTED",
            security_hardening="UNSUPPORTED",
        )

    @staticmethod
    def _read_stream(
        stream: typing.IO[bytes],
        chunks_list: list[bytes],
        truncated_flag: list[bool],
        max_bytes: int = 50_000,
    ) -> None:
        total_bytes = 0
        read_fn = getattr(stream, "read1", stream.read)
        while True:
            chunk = read_fn(4096)
            if not chunk:
                break

            if total_bytes < max_bytes:
                remaining = max_bytes - total_bytes
                chunks_list.append(chunk[:remaining])
                total_bytes += len(chunk)
                if len(chunk) > remaining:
                    truncated_flag[0] = True
            else:
                truncated_flag[0] = True

    def execute(
        self, command: list[str], policy: SandboxPolicy, timeout: int = 30
    ) -> SandboxResult:
        if platform.system() != "Linux":
            raise SandboxError("LinuxSandboxBackend is only available on Linux.")

        if policy.max_output_size < 0:
            raise SandboxError(
                f"max_output_size must be non-negative, got {policy.max_output_size}"
            )

        bwrap_path = shutil.which("bwrap")
        if not bwrap_path:
            raise SandboxError(
                "Secure Linux sandbox backend unavailable. "
                "Bubblewrap (bwrap) is required for namespace isolation."
            )

        workspace_path = policy.workspace_root.resolve().as_posix()

        bwrap_cmd = [
            bwrap_path,
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/bin",
            "/bin",
            "--ro-bind",
            "/sbin",
            "/sbin",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/lib64",
            "/lib64",
            "--ro-bind",
            "/etc/alternatives",
            "/etc/alternatives",
            "--ro-bind",
            "/etc/resolv.conf",
            "/etc/resolv.conf",
            "--ro-bind",
            "/etc/ssl",
            "/etc/ssl",
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--tmpfs",
            "/tmp",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--unshare-cgroup-try",
            "--bind",
            workspace_path,
            workspace_path,
        ]

        # Protect .git from read/write inside the sandbox.
        # - If .git is an existing directory: mount tmpfs with mode 0000 over it.
        # - If .git is a regular file (e.g. Git worktree) or symlink: mount /dev/null read-only.
        # - If .git does not exist on host: establish a transient sentinel directory with mode 0000
        #   and mount tmpfs with mode 0000 over it. This prevents the sandbox process from creating
        #   a .git directory or planting rogue hooks on the host.
        # Cross-process coordination protocol:
        # 1. Dedicated workspace IPC state directory in tempdir: velix_ws_<hash>/
        # 2. Master lock (master.lock) serialized briefly during setup and teardown.
        # 3. Active execution token (clients/token_<pid>_<thread_id>_<uuid>.token) held locked
        #    via fcntl.flock(LOCK_EX) throughout the Bubblewrap execution.
        # 4. Crashed processes automatically release token lock upon OS process termination;
        #    active tokens are discovered via non-blocking flock probes (EWOULDBLOCK).
        # 5. Exact device & inode identity (st_dev, st_ino) recorded in sentinel.info.
        git_path = Path(workspace_path) / ".git"
        canonical_ws = Path(workspace_path).resolve().as_posix()
        created_git_sentinel = False
        sentinel_identity: tuple[int, int] | None = None
        execution_exception: Exception | None = None

        lock_hash = hashlib.sha256(canonical_ws.encode("utf-8")).hexdigest()[:16]
        ipc_dir = Path(tempfile.gettempdir()) / f"velix_ws_{lock_hash}"
        master_lock_path = ipc_dir / "master.lock"
        clients_dir = ipc_dir / "clients"
        sentinel_info_path = ipc_dir / "sentinel.info"

        import uuid

        token_uid = uuid.uuid4().hex[:8]
        client_token_name = f"token_{os.getpid()}_{threading.get_ident()}_{token_uid}.token"
        client_token_path = clients_dir / client_token_name
        client_token_fd: int | None = None

        # Fail-closed helper for acquiring master lock
        def _acquire_master_lock() -> int:
            try:
                ipc_dir.mkdir(parents=True, exist_ok=True)
                clients_dir.mkdir(parents=True, exist_ok=True)
                fd = os.open(master_lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX)
                return fd
            except Exception as lock_exc:
                raise SandboxError(
                    f"Failed to acquire workspace master lock for {workspace_path}: {lock_exc}"
                ) from lock_exc

        def _release_master_lock(fd: int) -> None:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

        def _count_active_clients_and_prune() -> int:
            active = 0
            if not clients_dir.is_dir():
                return 0
            for child in clients_dir.iterdir():
                if not child.name.endswith(".token"):
                    continue
                try:
                    probe_fd = os.open(child, os.O_RDWR | os.O_CLOEXEC)
                    try:
                        fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        # Lock succeeded => owning process or thread is dead
                        fcntl.flock(probe_fd, fcntl.LOCK_UN)
                        os.close(probe_fd)
                        with contextlib.suppress(OSError):
                            child.unlink()
                    except (BlockingIOError, OSError):
                        # Lock busy => client is alive and holding flock
                        active += 1
                        os.close(probe_fd)
                except OSError:
                    pass
            return active

        # Step 1: Acquire master lock to register client token and inspect/create sentinel
        master_fd = _acquire_master_lock()
        try:
            try:
                client_token_fd = os.open(
                    client_token_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600
                )
                fcntl.flock(client_token_fd, fcntl.LOCK_EX)
            except Exception as client_exc:
                if client_token_fd is not None:
                    with contextlib.suppress(OSError):
                        os.close(client_token_fd)
                    with contextlib.suppress(OSError):
                        client_token_path.unlink()
                raise SandboxError(
                    f"Failed to acquire execution client token for {workspace_path}: {client_exc}"
                ) from client_exc

            _count_active_clients_and_prune()
            # Inspect host .git
            st_existing = None
            try:
                st_existing = os.lstat(git_path)
            except OSError:
                st_existing = None

            if st_existing is not None:
                import stat as pystat

                if pystat.S_ISDIR(st_existing.st_mode):
                    # Check if recorded sentinel info matches this directory
                    matched_sentinel = False
                    if sentinel_info_path.is_file():
                        try:
                            import json

                            info = json.loads(sentinel_info_path.read_text())
                            expected_id = (info.get("dev"), info.get("ino"))
                            if (st_existing.st_dev, st_existing.st_ino) == expected_id:
                                matched_sentinel = True
                        except Exception:
                            matched_sentinel = False
                    if matched_sentinel:
                        created_git_sentinel = True
                        sentinel_identity = (st_existing.st_dev, st_existing.st_ino)
                    bwrap_cmd.extend(["--perms", "0000", "--tmpfs", git_path.as_posix()])
                elif pystat.S_ISREG(st_existing.st_mode) or pystat.S_ISLNK(st_existing.st_mode):
                    bwrap_cmd.extend(["--ro-bind", "/dev/null", git_path.as_posix()])
            else:
                # .git does not exist: create transient sentinel
                try:
                    git_path.mkdir(exist_ok=False)
                    git_path.chmod(0o000)
                    st = os.lstat(git_path)
                    sentinel_identity = (st.st_dev, st.st_ino)
                    created_git_sentinel = True
                    import json

                    sentinel_info_path.write_text(
                        json.dumps({
                            "dev": sentinel_identity[0],
                            "ino": sentinel_identity[1],
                            "mode": 0,  # always 0o000
                            "pid": os.getpid(),
                        })
                    )
                    bwrap_cmd.extend(["--perms", "0000", "--tmpfs", git_path.as_posix()])
                except Exception as sentinel_exc:
                    logger.warning(
                        "Could not establish transient .git sentinel directory: %s", sentinel_exc
                    )
                    raise SandboxError(
                        f"Failed to establish transient .git sentinel for {workspace_path}: "
                        f"{sentinel_exc}"
                    ) from sentinel_exc
        finally:
            _release_master_lock(master_fd)

        sys_prefix = Path(sys.prefix).resolve()
        exec_file_resolved = Path(sys.executable).resolve()
        exec_file_unresolved = Path(sys.executable)
        workspace_resolved = Path(workspace_path).resolve()

        # Mount only the specific runtime paths needed (executable and libraries),
        # avoiding exposing the entire sys.prefix which could contain other binaries or secrets.
        paths_to_mount = {exec_file_resolved, exec_file_unresolved}

        # In a virtual environment, python relies on pyvenv.cfg at the prefix root.
        pyvenv_cfg = sys_prefix / "pyvenv.cfg"
        if pyvenv_cfg.exists():
            paths_to_mount.add(pyvenv_cfg.resolve())

        for lib_dir in ("lib", "lib64"):
            lib_path = sys_prefix / lib_dir
            if lib_path.exists():
                paths_to_mount.add(lib_path.resolve())

        for path_to_mount in paths_to_mount:
            is_covered = False
            for std_path in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
                if path_to_mount.is_relative_to(Path(std_path).resolve()):
                    is_covered = True
                    break

            if not is_covered and not path_to_mount.is_relative_to(workspace_resolved):
                bwrap_cmd.extend(["--ro-bind", path_to_mount.as_posix(), path_to_mount.as_posix()])

        if not policy.allow_network:
            bwrap_cmd.append("--unshare-net")

        bwrap_cmd.extend(["--", *command])

        has_cgroups = self._detect_systemd()
        scope_name = None
        if has_cgroups and (policy.memory_limit or policy.process_limit):
            import uuid

            scope_name = f"velix-sandbox-{uuid.uuid4().hex}.scope"
            systemd_cmd = [
                "systemd-run",
                "--user",
                "--scope",
                "-q",
                "--no-ask-password",
                f"--unit={scope_name}",
                "--property=CollectMode=inactive-or-failed",
            ]
            if policy.memory_limit:
                systemd_cmd.append(f"--property=MemoryMax={policy.memory_limit}")
            if policy.process_limit:
                systemd_cmd.append(f"--property=TasksMax={policy.process_limit}")

            bwrap_cmd = systemd_cmd + bwrap_cmd

        def set_limits() -> None:
            # Enforce CPU limit
            if policy.cpu_limit:
                with contextlib.suppress(Exception):
                    resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))  # type: ignore[attr-defined]

            # Memory Limit
            if policy.memory_limit:
                with contextlib.suppress(Exception):
                    resource.setrlimit(  # type: ignore[attr-defined]
                        resource.RLIMIT_AS,
                        (policy.memory_limit, policy.memory_limit),  # type: ignore[attr-defined]
                    )

            # Process Limit
            if policy.process_limit:
                with contextlib.suppress(Exception):
                    resource.setrlimit(  # type: ignore[attr-defined]
                        resource.RLIMIT_NPROC,
                        (policy.process_limit, policy.process_limit),  # type: ignore[attr-defined]
                    )

        try:
            # Environment filtering
            allowed_env = ["PATH", "HOME", "USER", "LANG", "LC_ALL"]
            env = {k: os.environ.get(k, "") for k in allowed_env if k in os.environ}
            # Explicity set TMPDIR to /tmp which is a tmpfs in bwrap
            env["TMPDIR"] = "/tmp"
            env.update(policy.env)

            logger.info(f"Executing sandboxed command: {' '.join(command)}")

            process = subprocess.Popen(
                bwrap_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=workspace_path,
                start_new_session=True,
                preexec_fn=set_limits,
            )

            stdout_chunks: list[bytes] = []
            stderr_chunks: list[bytes] = []
            stdout_truncated = [False]
            stderr_truncated = [False]

            out_thread = threading.Thread(
                target=self._read_stream,
                args=(process.stdout, stdout_chunks, stdout_truncated, policy.max_output_size),
            )
            err_thread = threading.Thread(
                target=self._read_stream,
                args=(process.stderr, stderr_chunks, stderr_truncated, policy.max_output_size),
            )
            out_thread.daemon = True
            err_thread.daemon = True
            out_thread.start()
            err_thread.start()

            timeout_expired = False
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timeout_expired = True
                # Note: os.killpg signals the process group leader. Descendant
                # processes that detach into a separate session or process group
                # may escape this signal. Bubblewrap's PID namespace and systemd
                # scope teardown in finally provide subsequent process cleanup.
                with contextlib.suppress(Exception):
                    os.killpg(process.pid, signal.SIGKILL)  # type: ignore[attr-defined]
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(Exception):
                        process.kill()
                    with contextlib.suppress(Exception):
                        process.wait(timeout=1.0)

            # Bound thread joins to avoid indefinite hangs if surviving or
            # detached descendants retain inherited pipe write handles.
            out_thread.join(timeout=1.0)
            err_thread.join(timeout=1.0)

            with contextlib.suppress(Exception):
                if not out_thread.is_alive() and process.stdout:
                    process.stdout.close()
            with contextlib.suppress(Exception):
                if not err_thread.is_alive() and process.stderr:
                    process.stderr.close()

            stdout_bytes = b"".join(stdout_chunks)
            stderr_bytes = b"".join(stderr_chunks)

            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")

            if stdout_truncated[0]:
                stdout_str += OUTPUT_TRUNCATION_MARKER
            if stderr_truncated[0]:
                stderr_str += OUTPUT_TRUNCATION_MARKER

            if timeout_expired:
                return SandboxResult(
                    stdout="",
                    stderr="Command timed out",
                    exit_code=-1,
                    command=command,
                    truncation_status={
                        "stdout": stdout_truncated[0],
                        "stderr": stderr_truncated[0],
                    },
                )

            return SandboxResult(
                stdout=stdout_str,
                stderr=stderr_str,
                exit_code=process.returncode,
                command=command,
                truncation_status={"stdout": stdout_truncated[0], "stderr": stderr_truncated[0]},
            )
        except Exception as exec_exc:
            execution_exception = exec_exc
            if isinstance(exec_exc, SandboxError):
                raise
            raise SandboxError(f"Failed to execute sandboxed command: {exec_exc}") from exec_exc
        finally:
            cleanup_err: Exception | None = None
            try:
                # Coordinate teardown under master lock
                master_fd = _acquire_master_lock()
                try:
                    # Release and unlink this execution's client token inside master lock
                    if client_token_fd is not None:
                        with contextlib.suppress(OSError):
                            fcntl.flock(client_token_fd, fcntl.LOCK_UN)
                            os.close(client_token_fd)
                        client_token_fd = None
                    with contextlib.suppress(OSError):
                        client_token_path.unlink()

                    rem_active = _count_active_clients_and_prune()
                    if rem_active == 0 and created_git_sentinel and sentinel_identity is not None:
                        # Attempt safe directory-descriptor-relative cleanup
                        parent_fd: int | None = None
                        try:
                            parent_fd = os.open(
                                workspace_path, os.O_DIRECTORY | os.O_RDONLY | os.O_CLOEXEC
                            )
                            # Check status relative to parent directory without following symlinks
                            st = os.stat(".git", dir_fd=parent_fd, follow_symlinks=False)
                            import stat as pystat

                            if (
                                not pystat.S_ISLNK(st.st_mode)
                                and pystat.S_ISDIR(st.st_mode)
                                and (st.st_dev, st.st_ino) == sentinel_identity
                                # Mode must still be 0o000: our sentinel is always created with
                                # chmod(0o000). On Linux, rmdir+mkdir can reuse the same inode
                                # immediately, causing a false-positive identity match. A genuine
                                # replacement directory will have a non-zero mode (e.g. 0o755).
                                and pystat.S_IMODE(st.st_mode) == 0o000
                            ):
                                # Atomic removal: POSIX rmdir operates on parent and does NOT
                                # require write permission on the target directory itself.
                                # Therefore no chmod(0700) is executed, eliminating the TOCTOU
                                # symlink retargeting window.
                                os.rmdir(".git", dir_fd=parent_fd)
                                with contextlib.suppress(OSError):
                                    sentinel_info_path.unlink()
                            else:
                                found_mode = oct(pystat.S_IMODE(st.st_mode))
                                recovery_msg = (
                                    f"Sentinel at {git_path} was replaced or has mismatched "
                                    f"identity or mode (expected id={sentinel_identity}, "
                                    f"mode=0o000; found id={(st.st_dev, st.st_ino)}, "
                                    f"mode={found_mode}). Leaving path untouched. "
                                    f"Manual recovery: verify contents and remove with "
                                    f"'chmod 700 {git_path} && rmdir {git_path}'."
                                )
                                logger.error(recovery_msg)
                                cleanup_err = SandboxError(recovery_msg)
                        except OSError as os_err:
                            msg = f"Failed to remove sentinel directory at {git_path}: {os_err}"
                            logger.error(msg)
                            cleanup_err = SandboxError(msg)
                            cleanup_err.__cause__ = os_err
                        finally:
                            if parent_fd is not None:
                                with contextlib.suppress(OSError):
                                    os.close(parent_fd)
                finally:
                    _release_master_lock(master_fd)
            except Exception as exc:
                cleanup_err = exc

            if cleanup_err is not None:
                logger.error(
                    "Security-relevant sentinel cleanup error on %s: %s",
                    git_path,
                    cleanup_err,
                )
                if execution_exception is not None:
                    raise SandboxError(
                        f"Sentinel cleanup failed ({cleanup_err}); "
                        f"original execution error: {execution_exception}"
                    ) from execution_exception
                raise SandboxError(f"Sentinel cleanup failed: {cleanup_err}") from cleanup_err
            if scope_name:
                with contextlib.suppress(Exception):
                    subprocess.run(
                        [
                            "systemctl",
                            "--user",
                            "--no-ask-password",
                            "kill",
                            "--kill-who=all",
                            "--signal=SIGKILL",
                            scope_name,
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                    )
                with contextlib.suppress(Exception):
                    subprocess.run(
                        [
                            "systemctl",
                            "--user",
                            "--no-ask-password",
                            "stop",
                            scope_name,
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                    )
