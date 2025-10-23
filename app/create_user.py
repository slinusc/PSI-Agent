#!/usr/bin/env python
"""
Command-line utility to create users for the Chainlit app.

Usage:
    python create_user.py <username> <password> [--admin]
"""

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

from dotenv import load_dotenv
from data_layer import SQLiteDataLayer

load_dotenv()

DB_PATH = Path("data/chainlit.db")
UPLOADS_DIR = Path("data/uploads")


def hash_password(password: str) -> str:
    """Hash a password using SHA256."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


async def create_user(username: str, password: str, is_admin: bool = False, update: bool = False):
    """Create a new user or update existing user in the database."""
    data_layer = SQLiteDataLayer(db_path=DB_PATH, uploads_dir=UPLOADS_DIR)

    # Check if user already exists
    existing = await data_layer.get_user(username)
    if existing and not update:
        print(f"❌ User '{username}' already exists! Use --update to modify.")
        return False

    # Create or update the user
    roles = ["admin", "user"] if is_admin else ["user"]
    password_hash = hash_password(password)

    if existing:
        # Update existing user
        def _update_user():
            with data_layer._connect() as conn:
                cursor = conn.cursor()
                import json
                metadata = {"roles": roles, "email": username}
                cursor.execute(
                    "UPDATE users SET password_hash = ?, metadata = ? WHERE username = ?",
                    (password_hash, json.dumps(metadata), username)
                )
                conn.commit()
        await data_layer._run(_update_user)
        role_str = "admin" if is_admin else "user"
        print(f"✅ User '{username}' updated successfully as {role_str}!")
    else:
        # Create new user
        await data_layer._create_password_user(
            username=username,
            password_hash=password_hash,
            metadata={"roles": roles, "email": username}
        )
        role_str = "admin" if is_admin else "user"
        print(f"✅ User '{username}' created successfully as {role_str}!")

    return True


async def list_users():
    """List all users in the database."""
    data_layer = SQLiteDataLayer(db_path=DB_PATH, uploads_dir=UPLOADS_DIR)

    # Direct database query to list all users
    def _list_users():
        with data_layer._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username, metadata, created_at FROM users ORDER BY created_at DESC")
            return cursor.fetchall()

    users = await data_layer._run(_list_users)

    if not users:
        print("No users found in the database.")
        return

    print("\n📋 Users:")
    print("-" * 80)
    for username, metadata_str, created_at in users:
        import json
        metadata = json.loads(metadata_str or "{}")
        roles = metadata.get("roles", [])
        role_display = ", ".join(roles) if roles else "user"
        print(f"  • {username:30} | Roles: {role_display:20} | Created: {created_at}")
    print("-" * 80)


async def delete_user(username: str):
    """Delete a user from the database."""
    data_layer = SQLiteDataLayer(db_path=DB_PATH, uploads_dir=UPLOADS_DIR)

    # Check if user exists
    existing = await data_layer.get_user(username)
    if not existing:
        print(f"❌ User '{username}' does not exist!")
        return False

    # Delete the user
    def _delete_user():
        with data_layer._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE username = ?", (username,))
            conn.commit()

    await data_layer._run(_delete_user)
    print(f"✅ User '{username}' deleted successfully!")
    return True


async def change_email(old_username: str, new_username: str):
    """Change a user's email/username."""
    data_layer = SQLiteDataLayer(db_path=DB_PATH, uploads_dir=UPLOADS_DIR)

    # Check if old user exists
    existing = await data_layer.get_user(old_username)
    if not existing:
        print(f"❌ User '{old_username}' does not exist!")
        return False

    # Check if new username is already taken
    new_existing = await data_layer.get_user(new_username)
    if new_existing:
        print(f"❌ Username '{new_username}' is already taken!")
        return False

    # Update username
    def _change_email():
        with data_layer._connect() as conn:
            cursor = conn.cursor()
            import json
            # Get current metadata and update email
            old_metadata = json.loads(existing.metadata or "{}")
            old_metadata["email"] = new_username

            cursor.execute(
                "UPDATE users SET username = ?, metadata = ? WHERE username = ?",
                (new_username, json.dumps(old_metadata), old_username)
            )
            conn.commit()

    await data_layer._run(_change_email)
    print(f"✅ User email changed from '{old_username}' to '{new_username}'!")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Manage users for the Chainlit PSI application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a regular user
  python create_user.py alice@psi.ch mypassword123

  # Create an admin user
  python create_user.py admin@psi.ch secretpass --admin

  # Update password or role
  python create_user.py alice@psi.ch newpassword --update
  python create_user.py alice@psi.ch samepassword --admin --update

  # Change email address
  python create_user.py --change-email old@psi.ch new@psi.ch

  # List all users
  python create_user.py --list

  # Delete a user
  python create_user.py --delete alice@psi.ch
        """
    )

    parser.add_argument("username", nargs="?", help="Username/email for the user")
    parser.add_argument("password", nargs="?", help="Password for the user")
    parser.add_argument("--admin", action="store_true", help="Create/update user with admin role")
    parser.add_argument("--update", action="store_true", help="Update existing user's password or role")
    parser.add_argument("--list", action="store_true", help="List all users")
    parser.add_argument("--delete", metavar="USERNAME", help="Delete a user")
    parser.add_argument("--change-email", nargs=2, metavar=("OLD_EMAIL", "NEW_EMAIL"),
                       help="Change a user's email address")

    args = parser.parse_args()

    # Handle list command
    if args.list:
        asyncio.run(list_users())
        return

    # Handle delete command
    if args.delete:
        asyncio.run(delete_user(args.delete))
        return

    # Handle email change command
    if args.change_email:
        asyncio.run(change_email(args.change_email[0], args.change_email[1]))
        return

    # Handle create/update user command
    if not args.username or not args.password:
        parser.print_help()
        print("\n❌ Error: username and password are required for user creation/update")
        sys.exit(1)

    asyncio.run(create_user(args.username, args.password, args.admin, args.update))


if __name__ == "__main__":
    main()
