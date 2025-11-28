import logging

# Создание таблицы bot_crm
CREATE_bot_crm_TABLE = '''
    CREATE TABLE IF NOT EXISTS services.bot_crm(
        business_id UUID UNIQUE,
        business_name TEXT,
        agent_id UUID NOT NULL PRIMARY KEY,
        agent_name TEXT,
        crm TEXT,
        crm_username TEXT,
        crm_password TEXT,
        crm_access_token TEXT,
        crm_refresh_token TEXT,

        created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
        updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
    );
'''

# Создание таблицы instagram_business
CREATE_instagram_business_TABLE = """
    CREATE TABLE IF NOT EXISTS services.instagram_business (
        business_id UUID,
        business_name TEXT,
        agent_id UUID,
        agent_name TEXT,
        instagram_id SERIAL PRIMARY KEY,
        webhook_instagram_id TEXT,
        auth_instagram_id TEXT UNIQUE,
        instagram_access_token TEXT NOT NULL,
        instagram_refresh_token TEXT,
        instagram_expires_at TIMESTAMPTZ NOT NULL,

        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
"""


# Создание таблицы whatsapp_business
CREATE_waba_TABLE = """
    CREATE TABLE IF NOT EXISTS services.waba (
        business_id UUID,
        business_name TEXT,
        agent_id UUID,
        agent_name TEXT,
        waba_id BIGSERIAL PRIMARY KEY,
        waba_phone_id TEXT,
        waba_phone_number_id TEXT,
        waba_phone_number TEXT,
        waba_business_id TEXT,
        waba_access_token TEXT,
        waba_expires_at TIMESTAMPTZ,

        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
"""

# Создание таблицы whatsapp
CREATE_whatsapp_TABLE = """
    CREATE TABLE IF NOT EXISTS services.whatsapp (
        business_id UUID PRIMARY KEY,
        business_name TEXT,
        agent_id UUID UNIQUE,
        agent_name TEXT,

        whatsapp_id BIGSERIAL UNIQUE,
        whatsapp_name TEXT,
        whatsapp_phone TEXT,
        whatsapp_contacts JSONB DEFAULT '[]'::jsonb,
        whatsapp_chats JSONB DEFAULT '[]'::jsonb,
        whatsapp_chat_history JSONB DEFAULT '[]'::jsonb,

        whatsapp_is_business BOOLEAN DEFAULT FALSE,
        whatsapp_avatar_url TEXT,
        whatsapp_avatar_local TEXT,
        whatsapp_raw JSONB DEFAULT '{}'::jsonb,

        whatsapp_access_token TEXT,
        whatsapp_expires_at TIMESTAMPTZ,

        session_name TEXT UNIQUE,
        session_data JSONB DEFAULT '[]'::jsonb,
        session_zip BYTEA,
        session_zip_ts TIMESTAMPTZ,
        session_ts TIMESTAMPTZ,
        whatsapp_last_init TIMESTAMPTZ,

        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
"""
CREATE_services_whatsapp_chats_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_services_whatsapp_chats_gin
        ON services.whatsapp USING GIN (whatsapp_chats);
"""
CREATE_services_whatsapp_chat_history_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_services_whatsapp_chat_history_gin
        ON services.whatsapp USING GIN (whatsapp_chat_history);
"""

CREATE_whatsapp_messages_TABLE = """
    CREATE TABLE IF NOT EXISTS services.whatsapp_messages (
        id BIGSERIAL PRIMARY KEY,
        business_id UUID NOT NULL,
        thread_id TEXT,
        customer_id TEXT,
        message_id TEXT,
        sender TEXT,
        author TEXT,
        body TEXT,
        ts TIMESTAMPTZ,
        is_from_me BOOLEAN,
        has_media BOOLEAN,
        raw JSONB,

        created_at TIMESTAMPTZ DEFAULT now()
    );
"""
CREATE_services_whatsapp_messages_thread_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_services_whatsapp_messages_business_thread_ts
        ON services.whatsapp_messages (business_id, thread_id, ts DESC);
"""
CREATE_whatsapp_messages_message_INDEX = """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_services_whatsapp_messages_business_messageid
        ON services.whatsapp_messages (business_id, message_id)
        WHERE message_id IS NOT NULL;
"""

# Создание таблицы bot_telegram
CREATE_bot_telegram_TABLE = '''
    CREATE TABLE IF NOT EXISTS services.bot_telegram(
        business_id UUID NOT NULL,
        business_name TEXT,
        agent_id UUID NOT NULL PRIMARY KEY,
        agent_name TEXT,
        agent_service TEXT,
        telegram_token TEXT NOT NULL,
        telegram_personal_chat_id TEXT,
        telegram_group_id TEXT,
        telegram_channel_id TEXT,

        CONSTRAINT fk_agent_id FOREIGN key(agent_id) REFERENCES bots.agent_configs(agent_id)
    );
'''

async def setup_tables_services(db_conn):
    """Создает таблицы в БД внутри схемы services, если они еще не существуют.
    """
    await db_conn.execute_query(CREATE_bot_crm_TABLE)
    await db_conn.execute_query(CREATE_bot_telegram_TABLE)
    await db_conn.execute_query(CREATE_instagram_business_TABLE)
    await db_conn.execute_query(CREATE_waba_TABLE)
    await db_conn.execute_query(CREATE_whatsapp_TABLE)

    await db_conn.execute_query(CREATE_services_whatsapp_chats_INDEX)
    await db_conn.execute_query(CREATE_services_whatsapp_chat_history_INDEX)

    await db_conn.execute_query(CREATE_whatsapp_messages_TABLE)
    await db_conn.execute_query(CREATE_services_whatsapp_messages_thread_INDEX)
    await db_conn.execute_query(CREATE_whatsapp_messages_message_INDEX)


    logging.debug(f'Все таблицы в схеме "services" успешно созданы.')