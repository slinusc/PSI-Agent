# User Management Guide

## Overview

The PSI-Agent Chainlit application uses a CLI-based user management system. All user operations (create, update, delete) are performed via the `create_user.py` command-line tool.

## User Management Tool

### Creating Users

```bash
# Create a regular user
python create_user.py alice@psi.ch password123

# Create an admin user
python create_user.py admin@psi.ch secretpass --admin
```

### Updating Users

```bash
# Change password
python create_user.py alice@psi.ch newpassword --update

# Promote user to admin
python create_user.py alice@psi.ch samepassword --admin --update

# Demote admin to regular user
python create_user.py admin@psi.ch samepassword --update
```

### Changing Email Address

```bash
# Change a user's email/username
python create_user.py --change-email old@psi.ch new@psi.ch
```

### Listing Users

```bash
# List all registered users
python create_user.py --list
```

Example output:
```
📋 Users:
--------------------------------------------------------------------------------
  • alice@psi.ch                | Roles: user                 | Created: 2025-10-23 10:15:32
  • admin@psi.ch                | Roles: admin, user          | Created: 2025-10-23 08:30:00
--------------------------------------------------------------------------------
```

### Deleting Users

```bash
# Delete a user account
python create_user.py --delete alice@psi.ch
```

## Security Notes

- All user registration must be done via CLI tool by administrators
- Passwords are hashed using SHA256 before storage
- User management actions are logged
- Admin users have access to settings panel and can manage models/prompts
- Regular users have restricted access (no settings, no theme switching, no MCP server management)

## Default Admin Account

Create the default admin account:

```bash
python create_user.py admin@psi.ch your_secure_password --admin
```

Store credentials in `.env` file for reference:
```bash
CHAINLIT_ADMIN_USERNAME=admin@psi.ch
CHAINLIT_ADMIN_PASSWORD=your_secure_password
```

## User Roles

### Admin Users
- Can access and modify chat settings (model, temperature, system prompt)
- Can use `/admin` commands (if implemented)
- Have full access to all features
- Created with `--admin` flag

### Regular Users
- Cannot modify settings
- Cannot change theme (fixed to light mode)
- Cannot add/remove MCP servers
- Can use all MCP tools (AccWiki, ELOG, WebSearch)
- Default role when created without `--admin` flag

## Quick Reference

```bash
# Create user
python create_user.py <email> <password> [--admin]

# Update user
python create_user.py <email> <new_password> --update [--admin]

# Change email
python create_user.py --change-email <old_email> <new_email>

# List users
python create_user.py --list

# Delete user
python create_user.py --delete <email>
```

## Troubleshooting

**Q: User can't log in**
A: Verify the user exists with `python create_user.py --list` and check credentials.

**Q: How do I reset a password?**
A: Use the update command: `python create_user.py user@psi.ch newpassword --update`

**Q: How do I make a user an admin?**
A: Use the update command with `--admin` flag: `python create_user.py user@psi.ch password --admin --update`

**Q: Can users register themselves?**
A: No, all user accounts must be created by administrators using the CLI tool.

**Q: What happens if I delete a user?**
A: The user account is permanently deleted from the database. Their chat history may remain until manually cleaned up.
