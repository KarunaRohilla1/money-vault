import os
from pathlib import Path

try:
    import psycopg2
    from psycopg2 import errors
except ImportError:
    psycopg2 = None
    errors = None


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "supabase" / "schema.sql"

IntegrityError = psycopg2.IntegrityError if psycopg2 else Exception


def get_database_url():
    for key in (
        "SUPABASE_DB_URL",
        "DATABASE_URL"
    ):
        value = os.environ.get(key)
        if value:
            return value

    try:
        import streamlit as st

        for key in (
            "SUPABASE_DB_URL",
            "DATABASE_URL"
        ):
            value = st.secrets.get(key)
            if value:
                return value

    except Exception:
        pass

    raise RuntimeError(
        "Supabase PostgreSQL credentials are not configured. "
        "Set SUPABASE_DB_URL or DATABASE_URL in environment variables "
        "or Streamlit secrets."
    )


def get_supabase_client():
    try:
        from supabase import create_client
    except ImportError as error:
        raise RuntimeError(
            "supabase-py is not installed. Install dependencies from requirements.txt."
        ) from error

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get(
        "SUPABASE_ANON_KEY"
    )

    try:
        import streamlit as st

        url = url or st.secrets.get("SUPABASE_URL")
        key = (
            key
            or st.secrets.get("SUPABASE_SERVICE_ROLE_KEY")
            or st.secrets.get("SUPABASE_ANON_KEY")
        )
    except Exception:
        pass

    if not url or not key:
        raise RuntimeError(
            "Supabase API credentials are not configured. "
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY."
        )

    return create_client(
        url,
        key
    )


def connect():
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is not installed. Install dependencies from requirements.txt."
        )

    database_url = get_database_url()
    connect_kwargs = {}

    if "sslmode=" not in database_url:
        connect_kwargs["sslmode"] = os.environ.get(
            "SUPABASE_DB_SSLMODE",
            "require"
        )

    raw_conn = psycopg2.connect(
        database_url,
        **connect_kwargs
    )
    return PostgresConnection(raw_conn)


def execute_schema():
    conn = connect()
    try:
        with SCHEMA_PATH.open("r", encoding="utf-8") as file:
            schema_sql = file.read()

        conn.cursor().execute(schema_sql)
        conn.commit()
    finally:
        conn.close()


def translate_sql(sql):
    return convert_placeholders(sql)


def convert_placeholders(sql):
    result = []
    in_single_quote = False
    index = 0

    while index < len(sql):
        char = sql[index]

        if char == "'":
            result.append(char)
            if in_single_quote and index + 1 < len(sql) and sql[index + 1] == "'":
                result.append(sql[index + 1])
                index += 2
                continue

            in_single_quote = not in_single_quote
            index += 1
            continue

        if char == "?" and not in_single_quote:
            result.append("%s")
        elif (
            char == "%"
            and not in_single_quote
            and index + 1 < len(sql)
            and sql[index + 1] == "s"
        ):
            result.append("%s")
            index += 1
        elif char == "%":
            result.append("%%")
        else:
            result.append(char)

        index += 1

    return "".join(result)


def inserted_table_name(sql):
    words = sql.strip().split()
    if len(words) < 3:
        return None

    if words[0].upper() != "INSERT" or words[1].upper() != "INTO":
        return None

    return words[2].strip('"')


def is_insert_query(sql):
    return sql.strip().upper().startswith("INSERT INTO ")


class PostgresCursor:
    def __init__(self, raw_cursor):
        self.raw_cursor = raw_cursor
        self.lastrowid = None

    @property
    def rowcount(self):
        return self.raw_cursor.rowcount

    def execute(self, sql, params=None):
        translated = translate_sql(sql)
        params = tuple(params or ())

        try:
            self.raw_cursor.execute(
                translated,
                params
            )
            self.capture_lastrowid(translated)
        except errors.UndefinedColumn:
            if "pin_plain" in translated:
                self.raw_cursor.connection.rollback()
                return self
            raise
        except errors.DuplicateColumn:
            self.raw_cursor.connection.rollback()
            return self
        except errors.DuplicateTable:
            self.raw_cursor.connection.rollback()
            return self

        return self

    def capture_lastrowid(self, sql):
        self.lastrowid = None

        if not is_insert_query(sql):
            return

        table_name = inserted_table_name(sql)
        if not table_name:
            return

        with self.raw_cursor.connection.cursor() as cursor:
            cursor.execute(
                "SAVEPOINT money_vault_lastrowid"
            )
            cursor.execute(
                "SELECT pg_get_serial_sequence(%s, 'id')",
                (table_name,)
            )
            sequence = cursor.fetchone()[0]

            if not sequence:
                cursor.execute(
                    "RELEASE SAVEPOINT money_vault_lastrowid"
                )
                return

            try:
                cursor.execute(
                    "SELECT currval(%s)",
                    (sequence,)
                )
                self.lastrowid = cursor.fetchone()[0]
                cursor.execute(
                    "RELEASE SAVEPOINT money_vault_lastrowid"
                )
            except errors.ObjectNotInPrerequisiteState:
                cursor.execute(
                    "ROLLBACK TO SAVEPOINT money_vault_lastrowid"
                )
                cursor.execute(
                    "RELEASE SAVEPOINT money_vault_lastrowid"
                )

    def fetchone(self):
        return self.raw_cursor.fetchone()

    def fetchall(self):
        return self.raw_cursor.fetchall()

    def close(self):
        self.raw_cursor.close()


class PostgresConnection:
    def __init__(self, raw_connection):
        self.raw_connection = raw_connection

    def cursor(self):
        return PostgresCursor(
            self.raw_connection.cursor()
        )

    def execute(self, sql, params=None):
        cursor = self.cursor()
        return cursor.execute(
            sql,
            params
        )

    def commit(self):
        self.raw_connection.commit()

    def rollback(self):
        self.raw_connection.rollback()

    def close(self):
        self.raw_connection.close()
