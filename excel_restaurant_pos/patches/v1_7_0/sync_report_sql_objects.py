"""Install the stored procedures kept under `report_sql/`.

New .sql files do not need a patch of their own: the `after_migrate` hook runs
the same sync on every migrate. This patch exists so the procedures land on the
migrate that introduces the folder, and so a forced re-install has an entry point
(`bench --site <site> execute
excel_restaurant_pos.patches.v1_7_0.sync_report_sql_objects.execute`).
"""

from excel_restaurant_pos.shared.sql_procedures.sync import sync_sql_objects


def execute():
	sync_sql_objects()
