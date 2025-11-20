# Database Migrations

This folder contains database migration scripts for schema evolution.

## Migration naming convention
- `001_initial_schema.sql` - Initial database schema
- `002_add_feature.sql` - Add new feature
- `003_modify_table.sql` - Modify existing table

## Usage

### SQLite
```bash
sqlite3 db.sqlite3 < db/migrations/001_initial_schema.sql
```

### PostgreSQL
```bash
psql -U username -d database_name -f db/migrations/001_initial_schema.sql
```

## Future migrations
Add new migration files here as the schema evolves.
