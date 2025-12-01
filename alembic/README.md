# Alembic Migrations

This directory contains Alembic configuration for database migrations in the transactoid project.

## Configuration

- **Migration scripts location**: `alembic/` (this directory)
- **Migration versions location**: `db/migrations/`
- **Database URL**: Read from `DATABASE_URL` environment variable (loaded from `.env` file in project root)

## Usage

### Setting the Database URL

The database URL is automatically loaded from the `.env` file in the project root. You can also set it as an environment variable:

```bash
export DATABASE_URL="postgresql://user:password@localhost/transactoid"
# or for SQLite:
export DATABASE_URL="sqlite:///./transactoid.db"
```

### Applying Migrations

To apply all pending migrations:

```bash
uv run alembic upgrade head
```

To apply migrations up to a specific revision:

```bash
uv run alembic upgrade <revision_id>
```

### Creating New Migrations

To auto-generate a migration based on model changes:

```bash
uv run alembic revision --autogenerate -m "Description of changes"
```

To create an empty migration file:

```bash
uv run alembic revision -m "Description of changes"
```

### Checking Migration Status

To see the current database revision:

```bash
uv run alembic current
```

To see migration history:

```bash
uv run alembic history
```

To see detailed history:

```bash
uv run alembic history --verbose
```

### Rolling Back Migrations

To roll back one migration:

```bash
uv run alembic downgrade -1
```

To roll back to a specific revision:

```bash
uv run alembic downgrade <revision_id>
```

To roll back all migrations:

```bash
uv run alembic downgrade base
```

### Example Workflow

1. Make changes to SQLAlchemy models in `services/db.py`
2. Generate a migration:
   ```bash
   uv run alembic revision --autogenerate -m "Add new column to transactions"
   ```
3. Review the generated migration file in `db/migrations/`
4. Apply the migration:
   ```bash
   uv run alembic upgrade head
   ```

## Notes

- Migrations are stored in `db/migrations/` directory
- The `alembic.ini` file in the project root contains the main configuration
- All models are imported in `alembic/env.py` for autogenerate support
- Always review auto-generated migrations before applying them
