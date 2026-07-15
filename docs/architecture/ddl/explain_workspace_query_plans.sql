-- Run against Preview workspace after representative rows exist.
EXPLAIN QUERY PLAN
SELECT finding_id, code, severity
FROM preview_findings
WHERE run_id = 'run-0000000000000000000000000000'
  AND blocking = 1
  AND finding_status = 'OPEN'
  AND finding_id > 0
ORDER BY blocking, finding_status, severity, finding_id
LIMIT 100;
