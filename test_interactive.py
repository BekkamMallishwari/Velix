from velix_agent.core.runtime import Runtime

runtime = Runtime.create()

res1 = runtime.agent.respond("My Name is Mallishwari")
print("User:", "My Name is Mallishwari")
print("Agent:", res1.text)
print("----------------")
res2 = runtime.agent.respond("what is my name")
print("User:", "what is my name")
print("Agent:", res2.text)
