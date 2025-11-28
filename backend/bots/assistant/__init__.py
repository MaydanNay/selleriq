import os
from dotenv import load_dotenv
from openai import AsyncOpenAI, responses
from agents import (
    enable_verbose_stdout_logging,
    set_default_openai_api,
    set_default_openai_client,
    set_default_openai_key,
    set_tracing_export_api_key,
    set_tracing_disabled,
    set_trace_processors
)

# Загрузка окружения
load_dotenv('src/config/.env', override=True)
openai_key = os.getenv('OPENAI_KEY')
client = AsyncOpenAI(api_key=openai_key)

# Конфиг OpenAI SDK
set_default_openai_key(openai_key, True)
set_default_openai_client(client, True)
set_default_openai_api(responses)
set_tracing_export_api_key(openai_key)
set_tracing_disabled(False)
set_trace_processors([])

# Если нужен более подробный stdout:
# enable_verbose_stdout_logging()
