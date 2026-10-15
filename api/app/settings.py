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
    ai_mail: bool = True  # the AI writes the wording of invitation e-mails; false = always the fixed wording

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

    # Inviting many candidates at once: the planner books slots only inside these hours, on these
    # days, with a gap after each interview. Times are in the interview time zone (below).
    interview_windows: str = "09:00-12:00,14:00-17:00"
    interview_gap_minutes: int = 15
    work_days: str = "Mon,Tue,Wed,Thu,Fri"  # Saturday and Sunday off

    # E-mail (Module 7): every invitation goes to the candidate's real address through the
    # company's own mail server. Works with Gmail, Google Workspace, Microsoft 365 or any SMTP server.
    # Leave SMTP_HOST empty to switch e-mail off: the interviewer then copies the link by hand.
    smtp_host: str = ""  # e.g. smtp.gmail.com or smtp.office365.com
    smtp_port: int = 587  # 587 = STARTTLS (the usual), 465 = SSL from the first byte
    smtp_user: str = ""  # the mailbox that sends, e.g. hiring@yourcompany.com
    smtp_password: str = ""  # for Gmail: a 16-letter App Password, NOT the normal password
    mail_from: str = ""  # e.g. "BJIT Hiring <hiring@bjit.com>"; empty = the SMTP_USER address
    public_base_url: str = "http://localhost:8080"  # the address candidates open; used in invite links
    interview_utc_offset_minutes: int = 360  # the time zone shown in e-mails: 360 = UTC+06:00 (Dhaka)

    # Google Calendar: every scheduled interview is put on this calendar of the Google account the
    # refresh token belongs to. "primary" = that account's own calendar. Empty = switched off.
    google_calendar_id: str = ""
    interview_minutes: int = 60  # how long the calendar entry and the invitation say the interview lasts

    # Older names for the same Gmail login, still read so an existing .env keeps working.
    gmail_user: str = ""
    gmail_app_password: str = ""

    # Who may open an account (UI refresh).
    # Your HR people type the code once, when they sign up. Keep SIGNUP_CODE empty to switch
    # sign-up off completely: then only the accounts you create yourself can log in.
    company_name: str = "TalentSight"
    signup_code: str = ""
    signup_email_domains: str = ""  # optional, e.g. "bjitgroup.com": only these addresses may sign up

    # Speech to text (AssemblyAI streaming)
    assemblyai_api_key: str = ""
    stt_model: str = "universal-3-6-pro"
    stt_host: str = "streaming.assemblyai.com"  # accounts in the EU use streaming.eu.assemblyai.com


settings = Settings()