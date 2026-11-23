"""
配置管理
统一从项目根目录的 .env 文件加载配置
"""

import os
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
# 路径: MiroFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)


class Config:
    """Flask配置类"""
    
    # Flask配置
    # Pflicht, kein Standardwert: ohne SECRET_KEY startet die App nicht (siehe validate()).
    SECRET_KEY = os.environ.get('SECRET_KEY', '')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'

    # Zugriffsschutz (Login). Pflicht, kein Standardwert: APP_PASSWORD muss in .env stehen.
    APP_PASSWORD = os.environ.get('APP_PASSWORD', '')
    # Admin-Passwort (nur Inhaber) – schaltet die Abrechnung/Margen frei. Pflicht, kein Standardwert.
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')

    # Frühere Standardwerte aus dem (öffentlichen) Git-Verlauf. Gelten als verbrannt:
    # Steht einer davon in der Umgebung, startet die App nicht.
    BURNED_SECRETS = frozenset({'mirofish-secret-key', 'werwolf123#', 'werwolf-admin#'})
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False
    
    # LLM配置（统一使用OpenAI格式）
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')

    # Modell für den KI-Onboarding-Assistenten (stärkeres Modell für bessere
    # Prompt-Generierung). Gleicher OpenRouter-Key/-Base-URL; Fallback: LLM_MODEL_NAME.
    WIZARD_MODEL_NAME = os.environ.get('WIZARD_MODEL_NAME') \
        or os.environ.get('LLM_MODEL_NAME', 'anthropic/claude-sonnet-5')

    # Abrechnung: USD->EUR-Näherungskurs + Standard-Abrechnungspreis pro Run
    EUR_PER_USD = float(os.environ.get('EUR_PER_USD', '0.92'))
    DEFAULT_BILLING_PRICE_EUR = float(os.environ.get('DEFAULT_BILLING_PRICE_EUR', '50'))

    # Kosten-Schutzschalter: harter Deckel pro Run in EUR. Übersteigt das
    # OpenRouter-Saldo-Delta diesen Wert während einer laufenden Simulation,
    # wird der Simulationsprozess abgebrochen. 0 = deaktiviert.
    # Im Admin-Bereich (Abrechnung) zur Laufzeit überschreibbar.
    MAX_COST_EUR = float(os.environ.get('MAX_COST_EUR', '15'))
    
    # Maschinen-Schnittstelle /api/v1 (für andere Tools). Leer = deaktiviert.
    EXTERNAL_API_KEY = os.environ.get('EXTERNAL_API_KEY', '')

    # Zep配置
    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')
    
    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # 文本处理配置
    DEFAULT_CHUNK_SIZE = 500  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠大小
    
    # OASIS模拟配置
    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(os.path.dirname(__file__), '../uploads/simulations')
    
    # OASIS平台可用动作配置
    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]
    
    # Report Agent配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    
    @classmethod
    def validate(cls) -> list[str]:
        """验证必要配置"""
        errors: list[str] = []
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY 未配置")
        if not cls.ZEP_API_KEY:
            errors.append("ZEP_API_KEY 未配置")
        for name in ('SECRET_KEY', 'APP_PASSWORD', 'ADMIN_PASSWORD'):
            value = getattr(cls, name)
            if not value:
                errors.append(f"{name} fehlt (Pflicht, es gibt keinen Standardwert)")
            elif value in cls.BURNED_SECRETS:
                errors.append(f"{name} nutzt einen öffentlich bekannten früheren Standardwert, bitte neu setzen")
        if cls.APP_PASSWORD and cls.APP_PASSWORD == cls.ADMIN_PASSWORD:
            errors.append("APP_PASSWORD und ADMIN_PASSWORD dürfen nicht gleich sein")
        return errors

