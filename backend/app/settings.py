from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    frontend_origin: str = "http://localhost:5173"
    database_url: str = "sqlite:///./data/talentbridge.db"
    recruiter_api_token: SecretStr = SecretStr("")
    llm_provider: str = "groq"
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = ""
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = ""
    ollama_base_url: str = ""
    ollama_model: str = ""
    embedding_model: str = ""
    embedding_max_length: int = Field(default=512, gt=0)
    chroma_path: str = "./data/chroma"
    elevenlabs_api_key: SecretStr = SecretStr("")
    elevenlabs_agent_id: str = ""
    elevenlabs_webhook_secret: SecretStr = SecretStr("")
    elevenlabs_phone_enabled: bool = False
    elevenlabs_phone_number_id: str = ""
    elevenlabs_phone_agent_id: str = ""
    elevenlabs_voice_enabled: bool = False
    elevenlabs_supervised: bool = False
    keenable_api_key: SecretStr = SecretStr("")
    tavily_api_key: SecretStr = SecretStr("")
    llama_cloud_api_key: SecretStr = SecretStr("")
    langfuse_public_key: str = ""
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_base_url: str = ""
    # JSON: {"groq": {"requests": 100, "tokens": 100000}}. Missing limits deny use.
    provider_budget_limits: dict[str, dict[str, float]] = Field(default_factory=dict)
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    session_duration_seconds: int = Field(default=360, ge=60, le=480)
    session_max_duration_seconds: int = Field(default=480, ge=60, le=480)
    guest_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    guest_max_workspaces: int = Field(default=100, ge=1)
    guest_max_cases: int = Field(default=20, ge=1)
    guest_max_operations: int = Field(default=30, ge=1)
    workflow_auto_process: bool = False
    planning_max_cv_pages: int = Field(default=10, ge=1, le=50)
    planning_allow_pending_review: bool = False
    planning_enable_tavily_fallback: bool = False
    planning_llamaparse_tier: str = ""
    llm_max_completion_tokens: int = Field(default=4096, ge=256, le=8192)
    interview_followups_enabled: bool = True
    gmail_client_id: str = ""
    gmail_client_secret: SecretStr = SecretStr("")
    gmail_redirect_uri: str = "http://localhost:5173/api/hr/gmail/callback"
    gmail_token_encryption_key: SecretStr = SecretStr("")
    email_send_enabled: bool = False
    email_daily_cap: int = Field(default=10, ge=1, le=100)
    email_pacing_seconds: int = Field(default=30, ge=0, le=3600)
    email_max_attempts: int = Field(default=3, ge=1, le=5)
    email_send_lease_seconds: int = Field(default=180, ge=120)
    max_cv_bytes: int = Field(default=1000000, gt=0)

    @field_validator("session_max_duration_seconds", mode="before")
    @classmethod
    def cap_legacy_duration(cls, value):
        # Foundation .env files used 1800; preserve startup while enforcing eight minutes.
        return min(int(value), 480)
