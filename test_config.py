from velix_agent.core.config import VelixConfig

config = VelixConfig()
print("default_provider:", config.default_provider)
print("openai_api_key configured:", config.openai_api_key is not None)
print("gemini_api_key configured:", config.gemini_api_key is not None)
