from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Every setting comes from an environment variable with the same name in capitals.

    Example: database_url is read from DATABASE_URL. A setting without a default
    is required: the API refuses to start if it is missing.
    """

    database_url: str

    # Login (Module 3)
    jwt_secret: str
    jwt_minutes: int = 480
    seed_interviewer_email: str
    seed_interviewer_password: str

    # Language model
    groq_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"

    # Public careers page (Module 4)
    careers_email: str = "careers@talentsight.local"

    # Public job posts on Blogger, through our Blogger MCP server (Module 4).
    # Leave BLOGGER_BLOG_ID empty to switch posting off (tests, or a laptop without the keys).
    blogger_blog_id: str = ""
    blogger_blog_url: str = ""  # e.g. https://talentsight.blogspot.com
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""

    # CV intake (Module 5)
    cv_upload_dir: str = "/data/cv_uploads"  # the cv_uploads Docker volume
    cv_max_mb: int = 5                       # largest CV file accepted
    cv_max_files: int = 25                   # most CVs in one upload
    cv_max_chars: int = 8000                 # CV text sent to the AI is cut here, to stay inside Groq's free limits

    # Applications through one shared Google Form (Module 5)
    google_form_id: str = ""          # from the form's EDIT link: docs.google.com/forms/d/<THIS PART>/edit
    google_form_url: str = ""         # the form's SHARE link: https://docs.google.com/forms/d/e/.../viewform
    google_form_job_field: str = ""   # the "Job code" question in a pre-filled link, e.g. entry.123456789

    # Screening agent (Module 5): leave empty to use LLM_MODEL
    screening_model: str = ""

        # LiveKit video server
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_url: str = "ws://localhost:7880"  # the address the BROWSER connects to
    livekit_server_url: str = "http://livekit:7880"  # the address the API container uses (Docker network)

    # Interviews (Module 7)
    join_early_minutes: int = 15  # a candidate can join this long before the start time
    invite_hours_after: int = 24  # an invite link stops working this long after the start time

    # E-mail (Module 7). In development every message goes to Mailpit, a fake inbox at http://localhost:8025
    smtp_host: str = "mailpit"  # leave empty to switch e-mail off
    smtp_port: int = 1025
    mail_from: str = "TalentSight <interviews@talentsight.local>"
    public_base_url: str = "http://localhost:8080"  # the address candidates open; used in invite links
    interview_utc_offset_minutes: int = 360  # the time zone shown in e-mails: 360 = UTC+06:00 (Dhaka)

    # Real e-mail through Gmail, for real addresses only. Everything else still goes to Mailpit.
    # Leave GMAIL_USER empty to keep ALL mail in Mailpit (the safe default, also used by the tests).
    gmail_user: str = ""  # the Gmail address that sends, e.g. talentsight.demo@gmail.com
    gmail_app_password: str = ""  # a 16-letter Gmail App Password, NOT the normal password
    real_mail_domains: str = "gmail.com,googlemail.com"  # addresses at these domains get real mail
    real_mail_only_to: str = ""  # optional safety list: if set, ONLY these addresses get real mail

    # Speech to text (AssemblyAI streaming)
    assemblyai_api_key: str = ""
    stt_model: str = "universal-3-6-pro"
    stt_host: str = "streaming.assemblyai.com"  # accounts in the EU use streaming.eu.assemblyai.com


settings = Settings()