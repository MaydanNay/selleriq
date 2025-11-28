async def setup_tables_auth(db_conn):
    # Расширение
    await db_conn.execute_query("""
        CREATE EXTENSION IF NOT EXISTS "pgcrypto";
    """)
    
    # Создание таблицы refresh_tokens 
    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS auth.refresh_tokens (
            jti UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL,
            role VARCHAR(20) NOT NULL CHECK (role IN ('user','business')),
            issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            revoked BOOLEAN NOT NULL DEFAULT FALSE,
            device_name TEXT, 
            ip TEXT, 
            user_agent TEXT,
                                
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON auth.refresh_tokens (user_id);
    """)
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_active_refresh_tokens ON auth.refresh_tokens(user_id)
        WHERE revoked = FALSE;
    """)
    await db_conn.execute_query("""
        CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_role ON auth.refresh_tokens(user_id, role)
        WHERE revoked = FALSE
    """)
    
    # Функция для updated_at
    await db_conn.execute_query("""
        CREATE OR REPLACE FUNCTION auth.set_timestamp()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Триггер для refresh_tokens
    await db_conn.execute_query("""
        DROP TRIGGER IF EXISTS trg_refresh_tokens_updated_at ON auth.refresh_tokens;
    """)
    await db_conn.execute_query("""
        CREATE TRIGGER trg_refresh_tokens_updated_at
        BEFORE UPDATE ON auth.refresh_tokens
        FOR EACH ROW
        EXECUTE FUNCTION auth.set_timestamp();
    """)

    # Таблица для сброса паролей
    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS auth.password_reset_tokens (
            user_phone TEXT NOT NULL,
            token_hash CHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
                                
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                
            PRIMARY KEY (user_phone, token_hash)
        );
    """)
    # Триггер для password_reset_tokens
    await db_conn.execute_query("""
        DROP TRIGGER IF EXISTS trg_password_reset_tokens_updated_at ON auth.password_reset_tokens;
    """)
    await db_conn.execute_query("""
        CREATE TRIGGER trg_password_reset_tokens_updated_at
        BEFORE UPDATE ON auth.password_reset_tokens
        FOR EACH ROW
        EXECUTE FUNCTION auth.set_timestamp();
    """)

    # Таблица для токенов удаления аккаунта
    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS auth.account_delete_tokens (
            user_id UUID NOT NULL,
            token_hash CHAR(64) NOT NULL,
                                
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            
            PRIMARY KEY(user_id, token_hash)
        );
    """)
    # Триггер для account_delete_tokens
    await db_conn.execute_query("""
        CREATE INDEX ON auth.account_delete_tokens (user_id);
    """)
    await db_conn.execute_query("""
        DROP TRIGGER IF EXISTS trg_account_delete_tokens_updated_at
            ON auth.account_delete_tokens;
    """)
    await db_conn.execute_query("""
        CREATE TRIGGER trg_account_delete_tokens_updated_at
            BEFORE UPDATE ON auth.account_delete_tokens
            FOR EACH ROW
            EXECUTE FUNCTION auth.set_timestamp();
    """)

    # Таблица связей аккаунтов
    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS auth.user_accounts (
            main_user_id UUID NOT NULL,
            account_type TEXT NOT NULL CHECK (account_type IN ('user','business')),
            account_id UUID NOT NULL,
            session_jti UUID NOT NULL,
                                
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                                
            PRIMARY KEY (main_user_id, account_type, account_id, session_jti)
        );
    """)

    # Триггер для user_accounts
    await db_conn.execute_query("""
        DROP TRIGGER IF EXISTS trg_user_accounts_updated_at ON auth.user_accounts;
    """)
    await db_conn.execute_query("""
        CREATE TRIGGER trg_user_accounts_updated_at
        BEFORE UPDATE ON auth.user_accounts
        FOR EACH ROW
        EXECUTE FUNCTION auth.set_timestamp();
    """)

    # Gmail
    await db_conn.execute_query("""
        CREATE TABLE IF NOT EXISTS auth.oauth_accounts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid,
            provider text NOT NULL,
            provider_user_id text NOT NULL,
            access_token text,
            refresh_token text,
            token_expires_at timestamptz,
            scopes text,
            meta jsonb,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now(),
            UNIQUE (user_id, provider, provider_user_id)
        );
    """)
