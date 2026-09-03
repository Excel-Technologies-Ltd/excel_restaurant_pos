-- Statement terminators must match the active DELIMITER, so the DROP runs
-- before the delimiter is switched for the procedure body.
DROP PROCEDURE IF EXISTS `GetEmployeeTimeclockSummary`;

DELIMITER //

CREATE PROCEDURE `GetEmployeeTimeclockSummary`(
    IN p_startDate DATE,
    IN p_endDate DATE,
    IN p_employee_id VARCHAR(100),
    IN p_page INT,
    IN p_pageSize INT
)
BEGIN
    -- Set default values if NULL
    SET p_startDate = IFNULL(p_startDate, CURDATE());
    SET p_endDate = IFNULL(p_endDate, CURDATE());
    SET p_page = IFNULL(p_page, 1);
    SET p_pageSize = IFNULL(p_pageSize, 20);
    
    -- If employee_id is empty string, treat as NULL
    IF p_employee_id = '' THEN
        SET p_employee_id = NULL;
    END IF;

    -- ============================================================
    -- FIX: Use RECURSIVE CTE for unlimited date range
    -- ============================================================
    WITH RECURSIVE DateRange AS (
        SELECT p_startDate as business_date
        UNION ALL
        SELECT DATE_ADD(business_date, INTERVAL 1 DAY)
        FROM DateRange
        WHERE DATE_ADD(business_date, INTERVAL 1 DAY) <= p_endDate
    ),
    AllEmployees AS (
        SELECT DISTINCT
            E.`name` as employee_id,
            E.employee_name,
            E.`role`
        FROM
            `tabArcPOS Employee` E
        WHERE EXISTS (
            SELECT 1 
            FROM `tabEmployee Timeclock Tracking` ETM 
            WHERE ETM.employee = E.`name`
            AND ETM.business_date >= p_startDate 
            AND ETM.business_date <= p_endDate
        )
        AND (p_employee_id IS NULL OR E.`name` = p_employee_id)
    ),
    EmployeeDailyData AS (
        SELECT 
            ae.employee_id,
            ae.employee_name,
            ae.`role`,
            dr.business_date,
            DATE_FORMAT(dr.business_date, '%a, %b %d') as day_label,
            ETM.first_check_in,
            ETM.last_check_out,
            COALESCE(ETM.total_paid_hours, 0) as total_paid_hours,
            COALESCE(ETM.timeclock_cost, 0) as timeclock_cost,
            COALESCE(ETM.total_payment, 0) as total_payment,
            TIME(ETM.first_check_in) as shift_start,
            TIME(ETM.last_check_out) as shift_end,
            ROW_NUMBER() OVER (PARTITION BY ae.employee_name ORDER BY dr.business_date ASC) as date_rank
        FROM AllEmployees ae
        CROSS JOIN DateRange dr
        LEFT JOIN `tabEmployee Timeclock Tracking` ETM 
            ON ETM.employee = ae.employee_id
            AND ETM.business_date = dr.business_date
    ),
    EmployeeSummary AS (
        SELECT 
            employee_id,
            employee_name,
            `role`,
            SUM(total_paid_hours) as total_hours,
            SUM(timeclock_cost) as total_cost,
            SUM(total_payment) as total_payment,
            COUNT(DISTINCT CASE WHEN total_paid_hours > 0 THEN business_date END) as working_days,
            ROUND(AVG(CASE WHEN total_paid_hours > 0 THEN total_paid_hours END), 2) as avg_daily_hours,
            COUNT(DISTINCT business_date) as total_days
        FROM EmployeeDailyData
        GROUP BY employee_id, employee_name, `role`
        ORDER BY total_hours DESC
    ),
    PaginatedSlots AS (
        SELECT 
            employee_id,
            employee_name,
            `role`,
            business_date,
            day_label,
            first_check_in,
            last_check_out,
            total_paid_hours,
            timeclock_cost,
            total_payment,
            shift_start,
            shift_end,
            date_rank
        FROM EmployeeDailyData
        WHERE date_rank BETWEEN ((p_page - 1) * p_pageSize + 1) AND (p_page * p_pageSize)
    ),
    DateSummary AS (
        SELECT 
            business_date,
            DATE_FORMAT(business_date, '%a, %b %d') as day_label,
            SUM(total_paid_hours) as total_hours,
            SUM(timeclock_cost) as total_cost,
            SUM(total_payment) as total_payment,
            COUNT(DISTINCT employee_name) as employee_count
        FROM EmployeeDailyData
        WHERE date_rank BETWEEN ((p_page - 1) * p_pageSize + 1) AND (p_page * p_pageSize)
        GROUP BY business_date
        ORDER BY business_date ASC
    )
    SELECT 
        JSON_OBJECT(
            'date_range', JSON_OBJECT(
                'start_date', p_startDate,
                'end_date', p_endDate,
                'total_days', DATEDIFF(p_endDate, p_startDate) + 1
            ),
            'pagination', JSON_OBJECT(
                'page', p_page,
                'pageSize', p_pageSize,
                'totalPages', CEIL((SELECT COUNT(DISTINCT business_date) FROM EmployeeDailyData) / p_pageSize),
                'hasNextPage', IF(p_page < CEIL((SELECT COUNT(DISTINCT business_date) FROM EmployeeDailyData) / p_pageSize), TRUE, FALSE),
                'hasPreviousPage', IF(p_page > 1, TRUE, FALSE)
            ),
            'date_summary', (
                SELECT JSON_ARRAYAGG(
                    JSON_OBJECT(
                        'date', ds.business_date,
                        'day', ds.day_label,
                        'total_hours', ds.total_hours,
                        'total_cost', ds.total_cost,
                        'total_payment', ds.total_payment,
                        'employee_count', ds.employee_count
                    )
                    ORDER BY ds.business_date ASC
                )
                FROM DateSummary ds
            ),
            'employees', (
                SELECT JSON_ARRAYAGG(
                    JSON_OBJECT(
                        'employee_id', es.employee_id,
                        'employee_name', es.employee_name,
                        'role', es.`role`,
                        'total_hours', es.total_hours,
                        'total_cost', es.total_cost,
                        'total_payment', es.total_payment,
                        'working_days', es.working_days,
                        'avg_daily_hours', es.avg_daily_hours,
                        'daily_slots', (
                            SELECT JSON_ARRAYAGG(
                                JSON_OBJECT(
                                    'date', ps.business_date,
                                    'day', ps.day_label,
                                    'check_in', IFNULL(TIME_FORMAT(ps.shift_start, '%l:%i %p'), ''),
                                    'check_out', IFNULL(TIME_FORMAT(ps.shift_end, '%l:%i %p'), ''),
                                    'hours_worked', ps.total_paid_hours,
                                    'cost', ps.timeclock_cost,
                                    'payment', ps.total_payment
                                )
                                ORDER BY ps.business_date ASC
                            )
                            FROM PaginatedSlots ps
                            WHERE ps.employee_name = es.employee_name
                        )
                    )
                )
                FROM EmployeeSummary es
            )
        ) AS json_result;
END //

DELIMITER ;