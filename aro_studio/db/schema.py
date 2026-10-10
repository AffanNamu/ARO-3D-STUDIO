"""Versioned schema. Append new migrations; never edit applied ones."""

from __future__ import annotations

MIGRATIONS: list[tuple[int, list[str]]] = [
    (
        1,
        [
            """CREATE TABLE projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""",
            """CREATE TABLE assets (
                asset_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DRAFT',
                metadata TEXT NOT NULL DEFAULT '{}',
                production_version_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""",
            "CREATE INDEX idx_assets_project ON assets(project_id)",
            "CREATE INDEX idx_assets_category ON assets(category)",
            """CREATE TABLE asset_versions (
                version_id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
                project_id TEXT NOT NULL,
                number INTEGER NOT NULL,
                label TEXT NOT NULL,
                stage TEXT NOT NULL,
                operation TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                parent_version_id TEXT,
                manifest_sha256 TEXT NOT NULL,
                vertex_count INTEGER NOT NULL DEFAULT 0,
                triangle_count INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                UNIQUE(asset_id, number)
            )""",
            "CREATE INDEX idx_versions_asset ON asset_versions(asset_id)",
            """CREATE TABLE jobs (
                job_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                project_id TEXT,
                asset_id TEXT,
                state TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                priority INTEGER NOT NULL DEFAULT 5,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 0,
                params TEXT NOT NULL DEFAULT '{}',
                result TEXT,
                error TEXT,
                resources TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL
            )""",
            "CREATE INDEX idx_jobs_state ON jobs(state)",
            "CREATE INDEX idx_jobs_project ON jobs(project_id)",
            """CREATE TABLE job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                ts REAL NOT NULL,
                level TEXT NOT NULL,
                state TEXT,
                message TEXT NOT NULL
            )""",
            "CREATE INDEX idx_job_events_job ON job_events(job_id)",
            """CREATE TABLE models (
                model_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                capability TEXT NOT NULL,
                source TEXT NOT NULL,
                license TEXT NOT NULL,
                license_status TEXT NOT NULL,
                commercial_use TEXT NOT NULL,
                requirements TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL
            )""",
            """CREATE TABLE model_versions (
                model_id TEXT NOT NULL REFERENCES models(model_id) ON DELETE CASCADE,
                version TEXT NOT NULL,
                revision TEXT,
                notes TEXT NOT NULL DEFAULT '',
                registered_at REAL NOT NULL,
                PRIMARY KEY (model_id, version)
            )""",
            """CREATE TABLE model_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                model_id TEXT NOT NULL,
                event TEXT NOT NULL,
                device TEXT,
                duration_s REAL,
                details TEXT NOT NULL DEFAULT '{}'
            )""",
            """CREATE TABLE generations (
                generation_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                job_id TEXT,
                engine_id TEXT NOT NULL,
                model_version TEXT NOT NULL,
                input_image_sha256 TEXT NOT NULL,
                input_path TEXT,
                settings TEXT NOT NULL DEFAULT '{}',
                cache_key TEXT NOT NULL,
                device TEXT,
                model_load_time_s REAL,
                execution_time_s REAL,
                output_format TEXT,
                output_sha256 TEXT,
                output_path TEXT,
                version_id TEXT,
                reused_from TEXT,
                status TEXT NOT NULL,
                error TEXT,
                created_at REAL NOT NULL
            )""",
            "CREATE INDEX idx_generations_cache ON generations(cache_key, status)",
            "CREATE INDEX idx_generations_asset ON generations(asset_id)",
            """CREATE TABLE materials (
                material_id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT NOT NULL REFERENCES asset_versions(version_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                data TEXT NOT NULL
            )""",
            """CREATE TABLE textures (
                texture_id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT NOT NULL REFERENCES asset_versions(version_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                sha256 TEXT NOT NULL
            )""",
            """CREATE TABLE lods (
                lod_id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT NOT NULL REFERENCES asset_versions(version_id) ON DELETE CASCADE,
                level INTEGER NOT NULL,
                triangle_count INTEGER NOT NULL,
                vertex_count INTEGER NOT NULL,
                target_ratio REAL
            )""",
            """CREATE TABLE exports (
                export_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                format TEXT NOT NULL,
                path TEXT NOT NULL,
                sha256 TEXT,
                size_bytes INTEGER,
                status TEXT NOT NULL,
                report TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            )""",
            "CREATE INDEX idx_exports_asset ON exports(asset_id)",
            """CREATE TABLE validation_results (
                validation_id TEXT PRIMARY KEY,
                version_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                overall REAL NOT NULL,
                status TEXT NOT NULL,
                critical_failures INTEGER NOT NULL,
                report TEXT NOT NULL,
                created_at REAL NOT NULL
            )""",
            "CREATE INDEX idx_validation_version ON validation_results(version_id)",
            """CREATE TABLE audit_log (
                audit_id TEXT PRIMARY KEY,
                ts REAL NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT,
                details TEXT NOT NULL DEFAULT '{}'
            )""",
            "CREATE INDEX idx_audit_ts ON audit_log(ts)",
        ],
    ),
]
