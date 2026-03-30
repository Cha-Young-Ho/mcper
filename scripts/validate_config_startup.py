#!/usr/bin/env python3
"""
Configuration validation script for MCPER startup.
Checks critical configuration issues before the app starts.

Usage:
    python scripts/validate_config_startup.py [--verbose]
"""

import sys
import os
from pathlib import Path

# ANSI color codes
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


class ConfigValidator:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.errors = []
        self.warnings = []
        self.infos = []

    def log_error(self, message: str):
        """Log an error (will cause exit code 1)."""
        self.errors.append(message)
        print(f"{RED}❌ ERROR:{RESET} {message}")

    def log_warning(self, message: str):
        """Log a warning (non-fatal)."""
        self.warnings.append(message)
        print(f"{YELLOW}⚠️  WARNING:{RESET} {message}")

    def log_info(self, message: str):
        """Log info message."""
        self.infos.append(message)
        if self.verbose:
            print(f"{GREEN}ℹ️  INFO:{RESET} {message}")

    def check_admin_password(self):
        """Check that admin password is not default."""
        try:
            from app.config import settings

            password = os.getenv("ADMIN_PASSWORD", settings.admin_password)
            if password == "changeme" or not password:
                self.log_error(
                    "Admin password is still 'changeme' or empty. "
                    "Set ADMIN_PASSWORD environment variable before production."
                )
            else:
                self.log_info("Admin password is configured.")
        except Exception as e:
            self.log_warning(f"Could not check admin password: {e}")

    def check_embedding_config(self):
        """Check embedding backend configuration."""
        try:
            from app.config import settings
            from app.services.embeddings.factory import build_embedding_backend

            provider = settings.embedding_provider.lower()
            self.log_info(f"Embedding provider: {provider}")

            # Try to instantiate backend (catches config errors early)
            try:
                backend = build_embedding_backend()
                dim = backend.get_embedding_dimension()

                if dim < 1 or dim > 4096:
                    self.log_error(
                        f"Embedding dimension {dim} is out of valid range [1, 4096]"
                    )
                else:
                    self.log_info(f"Embedding dimension: {dim} (valid)")
            except Exception as e:
                self.log_error(f"Failed to initialize embedding backend: {e}")
        except Exception as e:
            self.log_warning(f"Could not check embedding config: {e}")

    def check_redis_connectivity(self):
        """Check Redis/Celery connectivity."""
        try:
            from app.config import settings

            if not settings.celery_enabled:
                self.log_info("Celery is disabled (optional).")
                return

            # Try to connect to Redis
            try:
                import redis
                redis_url = os.getenv("REDIS_URL", settings.celery_broker_url)

                # Parse minimal connection info
                client = redis.from_url(redis_url, decode_responses=True)
                pong = client.ping()

                if pong:
                    self.log_info("Redis/Celery broker is reachable.")
                else:
                    self.log_warning("Redis ping returned False (may be offline).")
            except Exception as e:
                self.log_warning(f"Could not connect to Redis: {e}")
        except Exception as e:
            self.log_warning(f"Could not check Redis config: {e}")

    def check_db_connectivity(self):
        """Check database connectivity and schema."""
        try:
            from app.db.database import check_db_connection

            # Check basic connectivity
            try:
                check_db_connection()
                self.log_info("Database connection successful.")
            except Exception as e:
                self.log_error(f"Database connection failed: {e}")
                return

            # Check key tables exist
            try:
                from sqlalchemy import inspect, create_engine
                from app.config import settings

                engine = create_engine(settings.database_url)
                inspector = inspect(engine)
                tables = inspector.get_table_names()

                required_tables = ["global_rule_versions", "mcper_users", "specs"]
                missing = [t for t in required_tables if t not in tables]

                if missing:
                    self.log_warning(
                        f"Some expected tables are missing: {', '.join(missing)}. "
                        "Run database migrations if this is a new instance."
                    )
                else:
                    self.log_info("All required database tables exist.")

            except Exception as e:
                self.log_warning(f"Could not inspect database schema: {e}")
        except Exception as e:
            self.log_warning(f"Could not check database: {e}")

    def check_required_env_vars(self):
        """Check that required environment variables are set."""
        try:
            from app.config import settings

            required_vars = {}

            # AUTH_SECRET_KEY if auth is enabled
            if settings.auth_enabled:
                required_vars["AUTH_SECRET_KEY"] = os.getenv("AUTH_SECRET_KEY")

            # OPENAI_API_KEY if using OpenAI embeddings
            if "openai" in settings.embedding_provider.lower():
                required_vars["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

            # BEDROCK_REGION if using Bedrock embeddings
            if "bedrock" in settings.embedding_provider.lower():
                required_vars["BEDROCK_REGION"] = os.getenv("BEDROCK_REGION")

            missing = [k for k, v in required_vars.items() if not v]

            if missing:
                self.log_error(
                    f"Required environment variables not set: {', '.join(missing)}"
                )
            else:
                self.log_info("All required environment variables are configured.")
        except Exception as e:
            self.log_warning(f"Could not check environment variables: {e}")

    def run_all_checks(self):
        """Run all validation checks."""
        print(f"\n{BOLD}{BLUE}🔍 MCPER Configuration Validation{RESET}\n")

        self.check_admin_password()
        self.check_embedding_config()
        self.check_db_connectivity()
        self.check_redis_connectivity()
        self.check_required_env_vars()

        # Summary
        print(f"\n{BOLD}Summary:{RESET}")
        print(f"  Errors:   {len(self.errors)}")
        print(f"  Warnings: {len(self.warnings)}")
        print(f"  Infos:    {len(self.infos)}")

        if self.errors:
            print(
                f"\n{RED}{BOLD}❌ Configuration validation FAILED.{RESET} "
                f"Fix {len(self.errors)} error(s) before running the app."
            )
            return 1
        elif self.warnings:
            print(
                f"\n{YELLOW}{BOLD}⚠️  Configuration validation passed with warnings.{RESET}"
            )
            return 0
        else:
            print(f"\n{GREEN}{BOLD}✅ Configuration validation PASSED.{RESET}")
            return 0


def main():
    """Main entry point."""
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    validator = ConfigValidator(verbose=verbose)
    exit_code = validator.run_all_checks()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
