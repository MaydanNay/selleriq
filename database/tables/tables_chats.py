# Таблица contacts
CREATE_CONTACTS_TABLE = """
    CREATE TABLE IF NOT EXISTS chats.contacts (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL,
        user_name TEXT,
        service TEXT,
        access_token TEXT,
        phone_id UUID,
        contact_id UUID NOT NULL,
        contact_name TEXT,
        contact_avatar TEXT,
        thread_id UUID,
        contact_message JSONB DEFAULT '[]'::jsonb,
        user_response JSONB DEFAULT '[]'::jsonb,

        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
"""

# Таблица contact_messages
CREATE_CONTACT_MESSAGES_TABLE = """
    CREATE TABLE IF NOT EXISTS chats.contact_messages (
        id SERIAL PRIMARY KEY,
        user_id UUID NOT NULL,
        user_name TEXT,
        service TEXT,
        contact_id UUID NOT NULL,
        contact_name TEXT,
        contact_message JSONB DEFAULT '[]'::jsonb,
        user_response JSONB DEFAULT '[]'::jsonb,
        thread_id UUID,

        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
"""

CREATE_UNIQ_CONTACTS_IDX = """
CREATE UNIQUE INDEX IF NOT EXISTS uniq_user_contact_idx
  ON chats.contacts(user_id, contact_id);
"""
CREATE_IDX_CONTACTS_USER_ID = """
    CREATE INDEX IF NOT EXISTS idx_contacts_user_id
        ON chats.contacts(user_id);
"""
CREATE_IDX_CONTACTS_CONTACT_ID = """
    CREATE INDEX IF NOT EXISTS idx_contacts_contact_id
        ON chats.contacts(contact_id);
"""
CREATE_IDX_MSG_CONTACT_CREATED = """
    CREATE INDEX IF NOT EXISTS idx_msg_contact_created
        ON chats.contact_messages(contact_id, created_at DESC);
"""

async def setup_tables_chats(db_conn):
    """Создает таблицы в БД внутри схемы chats, если они еще не существуют.
    """
    await db_conn.execute_query(CREATE_CONTACTS_TABLE)
    await db_conn.execute_query(CREATE_CONTACT_MESSAGES_TABLE)
    await db_conn.execute_query(CREATE_UNIQ_CONTACTS_IDX)
    await db_conn.execute_query(CREATE_IDX_CONTACTS_USER_ID)
    await db_conn.execute_query(CREATE_IDX_CONTACTS_CONTACT_ID)
    await db_conn.execute_query(CREATE_IDX_MSG_CONTACT_CREATED)