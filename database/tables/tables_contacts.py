async def setup_tables_contacts(db_conn):
    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS contacts.contact_list (
            id BIGSERIAL PRIMARY KEY,
            business_id TEXT NOT NULL,
            service TEXT NOT NULL,
            contact_id TEXT,                -- whatsapp id вроде "7900...@c.us"
            phone TEXT NOT NULL,            -- нормализованный номер (только цифры)
            raw_phone TEXT,                 -- оригинальный номер (с +, пробелами)
            name TEXT,
            is_business BOOLEAN DEFAULT FALSE,
            avatar_url TEXT,
            wa_raw JSONB,                   -- оригинальный payload от whatsapp (опционально)
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    await db_conn.execute_query("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_business_phone 
            ON contacts.contact_list (business_id, phone);
    """)