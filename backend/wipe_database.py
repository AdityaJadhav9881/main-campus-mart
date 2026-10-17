"""
wipe_database.py
================
CLI executor for the hard reset wipe on Neon PostgreSQL.
Preserves all Admin and Super-Admin accounts while purging all operational
marketplace test records.
"""

import sys
from pathlib import Path

# Ensure /backend is on Python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import SessionLocal, engine
from app.schema_upgrade import upgrade_schema
from app.routers.admin import wipe_all_operational_data

def main():
    print("=== CAMPUSMART AI - HARD DATABASE RESET ===")
    print("Upgrading schema to ensure all columns (including role) exist...")
    upgrade_schema(engine)

    db = SessionLocal()
    try:
        print("Executing wipe_all_operational_data...")
        result = wipe_all_operational_data(db)
        print("\n--- WIPE RESULT ---")
        print(f"Status: {result['status']}")
        print(f"Message: {result['message']}")
        print("\nDeleted Record Counts:")
        for table, count in result["deleted"].items():
            print(f"  • {table}: {count}")
        print("\nPreserved Admin Accounts:")
        for admin in result["preserved_admins"]:
            print(f"  [OK] {admin['email']} ({admin['name']}) [Role: {admin['role']}]")
    finally:
        db.close()
    print("\n=== HARD RESET COMPLETE ===")

if __name__ == "__main__":
    main()
