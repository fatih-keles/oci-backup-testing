from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Any

from .config import AppConfig
from .oci_clients import OciClients


@dataclass(frozen=True)
class ReportUpload:
    namespace: str
    bucket_name: str
    object_name: str
    etag: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "namespace": self.namespace,
            "bucket_name": self.bucket_name,
            "object_name": self.object_name,
            "etag": self.etag,
            "uri": f"oci://{self.bucket_name}@{self.namespace}/{self.object_name}",
        }


BRAND = {
    # Derived from Redwood-ColorUpdateCMYK-ALL_2025.ase CMYK swatches.
    "paper": "#F5F5F5",       # Neutral 10
    "surface": "#FFFFFF",     # White
    "text": "#302F2E",        # Neutral 150
    "muted": "#716864",       # Neutral 100
    "line": "#D8D3CF",        # Neutral 50
    "accent": "#AA582B",      # Sienna 100
    "accent_soft": "#FAEBD4", # Sienna 30
    "success": "#2F6A26",     # Pine 130
    "success_soft": "#C9FFC7",# Pine 40
    "danger": "#7E4572",      # Rose 110
    "danger_soft": "#FAE6F7", # Rose 30
    "info": "#2E6D7B",        # Ocean 130
    "info_soft": "#CCF2ED",   # Ocean 40
}


def publish_report(
    clients: OciClients,
    config: AppConfig,
    results: list[dict[str, Any]],
    batch: dict[str, Any] | None = None,
) -> ReportUpload | None:
    if not config.report.enabled:
        return None
    if config.report.bucket_name is None:
        raise ValueError("report.bucket_name is required when report.enabled is true")

    html = render_report(config, results, batch=batch)
    namespace = config.report.namespace or clients.object_storage.get_namespace().data
    object_name = report_object_name(config, batch_id=(batch or {}).get("batch_id"))
    response = clients.object_storage.put_object(
        namespace,
        config.report.bucket_name,
        object_name,
        html.encode("utf-8"),
        content_type="text/html; charset=utf-8",
    )
    return ReportUpload(
        namespace=namespace,
        bucket_name=config.report.bucket_name,
        object_name=object_name,
        etag=getattr(response, "headers", {}).get("etag")
        or getattr(response, "headers", {}).get("ETag"),
    )


def report_object_name(
    config: AppConfig,
    now: datetime | None = None,
    batch_id: str | None = None,
) -> str:
    generated_at = now or datetime.now(timezone.utc)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    prefix = config.report.object_name_prefix.strip("/")
    filename = (
        f"oci-backup-validation-batch-{batch_id}.html"
        if batch_id
        else f"oci-backup-validation-{stamp}.html"
    )
    return f"{prefix}/{filename}" if prefix else filename


def render_report(
    config: AppConfig,
    results: list[dict[str, Any]],
    batch: dict[str, Any] | None = None,
) -> str:
    generated_at = datetime.now(timezone.utc)
    total = len(results)
    total_vms = sum(1 for result in results if result.get("instance_id"))
    total_disks = sum(_disk_count(result) for result in results)
    passed = sum(1 for result in results if _validation_passed(result) is True)
    failed = sum(1 for result in results if _validation_passed(result) is False)
    pending = total - passed - failed

    volume_group_rows = "\n".join(_volume_group_row(result) for result in results)
    vm_rows = "\n".join(_vm_row(result) for result in results)
    disk_rows = "\n".join(_disk_rows(result) for result in results)

    if not volume_group_rows:
        volume_group_rows = _empty_row(
            11,
            "No volume group restore executions were included in this report.",
        )
    if not vm_rows:
        vm_rows = _empty_row(9, "No test VM executions were included in this report.")
    if not disk_rows:
        disk_rows = _empty_row(6, "No restored disks were included in this report.")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(config.report.title)}</title>
  <style>
    :root {{
      --paper: {BRAND["paper"]};
      --surface: {BRAND["surface"]};
      --text: {BRAND["text"]};
      --muted: {BRAND["muted"]};
      --line: {BRAND["line"]};
      --accent: {BRAND["accent"]};
      --accent-soft: {BRAND["accent_soft"]};
      --success: {BRAND["success"]};
      --success-soft: {BRAND["success_soft"]};
      --danger: {BRAND["danger"]};
      --danger-soft: {BRAND["danger_soft"]};
      --info: {BRAND["info"]};
      --info-soft: {BRAND["info_soft"]};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--text);
      font-family: Arial, Helvetica, sans-serif;
      font-size: 14px;
      line-height: 1.45;
    }}
    .page {{
      width: 100%;
      margin: 0;
      padding: 36px 28px 48px;
    }}
    header {{
      border-top: 6px solid var(--accent);
      padding: 24px 0 18px;
    }}
    .eyebrow {{
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 8px 0 8px;
      font-size: 30px;
      line-height: 1.15;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .lede {{
      margin: 0;
      color: var(--muted);
      max-width: 760px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin: 24px 0;
    }}
    .metric {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 16px;
    }}
    .metric .label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .06em;
    }}
    .metric .value {{
      margin-top: 6px;
      font-size: 28px;
      font-weight: 700;
    }}
    .details {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
    }}
    .details + .details {{
      margin-top: 20px;
    }}
    .details-head {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      padding: 18px 20px;
      border-bottom: 1px solid var(--line);
    }}
    .details-head h2 {{
      margin: 0;
      font-size: 18px;
    }}
    .details-head p {{
      margin: 3px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #FBFAF9;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .05em;
    }}
    td {{
      font-size: 13px;
    }}
    tr:last-child td {{
      border-bottom: none;
    }}
    .name {{
      font-weight: 700;
    }}
    .ocid {{
      display: block;
      margin-top: 3px;
      color: var(--muted);
      font-family: Consolas, "Courier New", monospace;
      font-size: 11px;
      word-break: break-all;
    }}
    .badge {{
      display: inline-block;
      min-width: 76px;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 12px;
      font-weight: 700;
      text-align: center;
    }}
    .passed {{ background: var(--success-soft); color: var(--success); }}
    .failed {{ background: var(--danger-soft); color: var(--danger); }}
    .pending {{ background: var(--info-soft); color: var(--info); }}
    .meta {{
      margin-top: 20px;
      color: var(--muted);
      font-size: 12px;
    }}
    .empty {{
      color: var(--muted);
      text-align: center;
      padding: 28px;
    }}
    @media print {{
      body {{ background: #fff; }}
      .page {{ padding: 20px; }}
      .summary {{ grid-template-columns: repeat(4, 1fr); }}
    }}
    @media (max-width: 840px) {{
      .summary {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .details {{ overflow-x: auto; }}
      table {{ min-width: 960px; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <header>
      <div class="eyebrow">Oracle Cloud Infrastructure</div>
      <h1>{escape(config.report.title)}</h1>
      <p class="lede">Restore validation evidence for tagged OCI volume group backups. This report records the restored resources, launched test instances, block-volume attachment checks, and final control-plane test status.</p>
    </header>

    <section class="summary" aria-label="Report summary">
      {_metric("Volume groups", total)}
      {_metric("Test VMs", total_vms)}
      {_metric("Restored disks", total_disks)}
      {_metric("Pending or failed", pending + failed)}
    </section>

    <section class="details">
      <div class="details-head">
        <div>
          <h2>Volume Group Evidence</h2>
          <p>Generated {escape(generated_at.strftime("%Y-%m-%d %H:%M:%S UTC"))}</p>
          {_batch_line(batch)}
        </div>
        <div>
          <p>Source compartment: {escape(_short(config.source_compartment_id))}</p>
          <p>Target compartment: {escape(_short(config.target_compartment_id))}</p>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Test ID</th>
            <th>Source</th>
            <th>Backup policy</th>
            <th>Backup</th>
            <th>Restored volume group</th>
            <th># disks</th>
            <th>Test VM</th>
            <th>Boot volume</th>
            <th>Block volumes</th>
            <th>Evidence ID</th>
          </tr>
        </thead>
        <tbody>
          {volume_group_rows}
        </tbody>
      </table>
    </section>

    <section class="details">
      <div class="details-head">
        <div>
          <h2>VM Evidence</h2>
          <p>Test instance launch and attachment evidence for each restored VM.</p>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Test ID</th>
            <th>Source</th>
            <th>Backup</th>
            <th># disks attached</th>
            <th>Test VM</th>
            <th>Boot volume</th>
            <th>Block volumes</th>
            <th>Evidence ID</th>
          </tr>
        </thead>
        <tbody>
          {vm_rows}
        </tbody>
      </table>
    </section>

    <section class="details">
      <div class="details-head">
        <div>
          <h2>Disk Evidence</h2>
          <p>Restored boot and block volume evidence by disk.</p>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Test ID</th>
            <th>Attached VM name</th>
            <th>Boot/block volume</th>
            <th>Size</th>
            <th>Evidence ID</th>
          </tr>
        </thead>
        <tbody>
          {disk_rows}
        </tbody>
      </table>
    </section>

    <p class="meta">Validation scope: OCI control plane. The report confirms lifecycle states for restored volume groups, launched test instances, and volume attachments.</p>

    <section class="details">
      <div class="details-head">
        <div>
          <h2>Standards and Control Mapping</h2>
          <p>Use this section to map the restore test evidence to the frameworks that apply to the organization. Do not claim compliance with a framework unless the broader control set has been assessed.</p>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Framework / Regulation</th>
            <th>Relevant Control Area</th>
            <th>Evidence Expected in This Report</th>
            <th>Report Section</th>
          </tr>
        </thead>
        <tbody>
          {_standards_mapping_rows()}
        </tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def _metric(label: str, value: int) -> str:
    return (
        "<div class=\"metric\">"
        f"<div class=\"label\">{escape(label)}</div>"
        f"<div class=\"value\">{value}</div>"
        "</div>"
    )


def _standards_mapping_rows() -> str:
    rows = [
        (
            "NIST SP 800-53 Rev. 5",
            "Contingency Planning controls, including contingency plan testing, system backup, and system recovery.",
            "Test scope, backup asset used, restore result, RTO/RPO measurement, evidence, and remediation.",
            "Sections 5-13",
        ),
        (
            "NIST SP 800-34 Rev. 1",
            "Contingency planning, system recovery priorities, plan testing, and maintenance.",
            "Documented recovery strategy validation and test results against business requirements.",
            "Sections 5-8, 13",
        ),
        (
            "CIS Controls v8.1 - Control 11",
            "Data recovery process, automated backups, protected recovery data, isolated recovery data, and data recovery testing.",
            "Quarterly or more frequent sample-based restore testing, count tested, count working, count failed, time since last test.",
            "Sections 3, 7, 9-11",
        ),
        (
            "ISO/IEC 27001:2022 / ISO/IEC 27002:2022",
            "Information backup, ICT readiness, business continuity, and control evidence.",
            "Backup policy reference, recovery validation, owner approval, and evidence retained.",
            "Sections 4-13",
        ),
        (
            "HIPAA Security Rule, 45 CFR 164.308(a)(7)",
            "Contingency plan, data backup plan, disaster recovery plan, testing and revision procedures, and application/data criticality analysis for ePHI systems.",
            "Recoverability evidence for systems handling ePHI, criticality, and tested revision records.",
            "Sections 5-13",
        ),
        (
            "PCI DSS / financial-sector / customer contractual controls",
            "Business continuity, incident response, backup and recovery evidence, and resilience testing where applicable.",
            "Restore evidence linked to in-scope systems, data handling controls, and remediation records.",
            "Sections 4-13",
        ),
        (
            "Sama Rulebook",
            "Data Backup and Recoverability",
            "The effectiveness of the backup and restoration procedure should be measured and periodically evaluated. Member Organizations should conduct periodic testing and validation of the recovery capability of backup media.",
            "Sections 3.3.10-11",
        ),
        (
            "NCA Essential Cybersecurity Controls (ECC - 1 : 2018)",
            "Backup and Recovery Management",
            "2-9-3-3 Periodic tests of backup's recovery effectiveness.",
            "Sections 2-9-3-3",
        ),
    ]
    return "\n".join(
        "          <tr>"
        f"<td>{escape(framework)}</td>"
        f"<td>{escape(control_area)}</td>"
        f"<td>{escape(evidence)}</td>"
        f"<td>{escape(report_section)}</td>"
        "</tr>"
        for framework, control_area, evidence, report_section in rows
    )


def _batch_line(batch: dict[str, Any] | None) -> str:
    if not batch:
        return ""
    batch_id = escape(str(batch.get("batch_id") or ""))
    created_at = escape(str(batch.get("created_at") or ""))
    return f"<p>Batch: {batch_id} | Started: {created_at}</p>"


def _empty_row(colspan: int, message: str) -> str:
    return f"<tr><td colspan=\"{colspan}\" class=\"empty\">{escape(message)}</td></tr>"


def _volume_group_row(result: dict[str, Any]) -> str:
    status = (
        _status_for_check(
            result,
            "restored_volume_group_available",
            result.get("restored_volume_group_id"),
        )
        if result.get("restored_volume_group_id")
        else "PENDING"
    )
    status_class = status.lower().replace(" ", "-")
    return f"""
          <tr>
            <td><span class="badge {escape(status_class)}">{escape(status)}</span></td>
            <td>{_test_id(result)}</td>
            <td>{_resource(result.get("source_display_name"), result.get("source_volume_group_id"))}</td>
            <td>{_text_or_na(_backup_policy(result))}</td>
            <td>{_backup_cell(result)}</td>
            <td>{_resource(result.get("restored_volume_group_display_name"), result.get("restored_volume_group_id"))}</td>
            <td><span class="name">{_disk_count(result)}</span></td>
            <td>{_resource(result.get("instance_display_name"), result.get("instance_id"))}</td>
            <td>{_boot_volume_cell(result)}</td>
            <td>{_block_volumes_cell(result)}</td>
            <td>{_evidence_id(result.get("restored_volume_group_id"))}</td>
          </tr>"""


def _vm_row(result: dict[str, Any]) -> str:
    status = (
        _status_for_check(result, "instance_running", result.get("instance_id"))
        if result.get("instance_id")
        else "PENDING"
    )
    status_class = status.lower().replace(" ", "-")
    return f"""
          <tr>
            <td><span class="badge {escape(status_class)}">{escape(status)}</span></td>
            <td>{_test_id(result)}</td>
            <td>{_resource(result.get("source_display_name"), result.get("source_volume_group_id"))}</td>
            <td>{_backup_cell(result)}</td>
            <td><span class="name">{_attached_disk_count(result)} / {_disk_count(result)}</span></td>
            <td>{_resource(result.get("instance_display_name"), result.get("instance_id"))}</td>
            <td>{_boot_volume_cell(result)}</td>
            <td>{_block_volumes_cell(result)}</td>
            <td>{_evidence_id(result.get("instance_id"))}</td>
          </tr>"""


def _disk_rows(result: dict[str, Any]) -> str:
    rows = []
    if result.get("boot_volume_id"):
        boot_status = (
            _status_for_check(result, "instance_running", result.get("instance_id"))
            if result.get("instance_id")
            else "PENDING"
        )
        rows.append(
            _disk_row(
                status=boot_status,
                test_id=result.get("run_id"),
                attached_vm_name=result.get("instance_display_name"),
                volume_name=_boot_volume_name(result),
                volume_kind="Boot volume",
                size_in_gbs=result.get("boot_volume_size_in_gbs"),
                evidence_id=result.get("boot_volume_id"),
            )
        )

    block_ids = result.get("block_volume_ids") or []
    block_names = result.get("block_volume_display_names") or []
    block_sizes = result.get("block_volume_sizes_in_gbs") or []
    attachment_ids = result.get("volume_attachment_ids") or []
    for index, volume_id in enumerate(block_ids):
        attachment_id = attachment_ids[index] if index < len(attachment_ids) else None
        block_status = (
            _status_for_check(result, "block_volume_attached", attachment_id)
            if attachment_id
            else "PENDING"
        )
        rows.append(
            _disk_row(
                status=block_status,
                test_id=result.get("run_id"),
                attached_vm_name=result.get("instance_display_name"),
                volume_name=_indexed_value(block_names, index)
                or f"Restored block volume {index + 1}",
                volume_kind="Block volume",
                size_in_gbs=_indexed_value(block_sizes, index),
                evidence_id=volume_id,
            )
        )
    return "\n".join(rows)


def _disk_row(
    *,
    status: str,
    test_id: Any,
    attached_vm_name: Any,
    volume_name: Any,
    volume_kind: str,
    size_in_gbs: Any,
    evidence_id: Any,
) -> str:
    status_class = status.lower().replace(" ", "-")
    return f"""
          <tr>
            <td><span class="badge {escape(status_class)}">{escape(status)}</span></td>
            <td>{_plain_id(test_id)}</td>
            <td>{_text_or_na(attached_vm_name)}</td>
            <td><span class="name">{escape(volume_kind)}</span><span class="ocid">{escape(str(volume_name or "Not available"))}</span></td>
            <td>{_size_label(size_in_gbs)}</td>
            <td>{_evidence_id(evidence_id)}</td>
          </tr>"""


def _resource(name: Any, ocid: Any) -> str:
    safe_name = escape(str(name or "Not available"))
    safe_ocid = escape(str(ocid or ""))
    return f"<span class=\"name\">{safe_name}</span><span class=\"ocid\">{safe_ocid}</span>"


def _backup_cell(result: dict[str, Any]) -> str:
    name = result.get("latest_backup_display_name") or "Not available"
    created = result.get("latest_backup_time_created")
    created_html = f"<span class=\"ocid\">{escape(str(created))}</span>" if created else ""
    return f"<span class=\"name\">{escape(str(name))}</span>{created_html}"


def _backup_policy(result: dict[str, Any]) -> str | None:
    backup_name = str(result.get("latest_backup_display_name") or "")
    match = re.search(r"\bvia policy:\s*(.*?)\s+on\s+\d{4}-\d{2}-\d{2}", backup_name)
    if match:
        return match.group(1).strip() or None
    match = re.search(r"\bpolicy:\s*(.*)$", backup_name)
    if match:
        return match.group(1).strip() or None
    return None


def _test_id(result: dict[str, Any]) -> str:
    return _plain_id(result.get("run_id"))


def _plain_id(value: Any) -> str:
    return f"<span class=\"ocid\">{escape(str(value or 'Not available'))}</span>"


def _evidence_id(value: Any) -> str:
    return _plain_id(value)


def _text_or_na(value: Any) -> str:
    return escape(str(value or "Not available"))


def _boot_volume_cell(result: dict[str, Any]) -> str:
    return _resource(_boot_volume_name(result), result.get("boot_volume_id"))


def _boot_volume_name(result: dict[str, Any]) -> str | None:
    name = result.get("boot_volume_display_name")
    if not name and result.get("boot_volume_id"):
        return "Restored boot volume"
    return name


def _block_volumes_cell(result: dict[str, Any]) -> str:
    block_ids = result.get("block_volume_ids") or []
    block_names = result.get("block_volume_display_names") or []
    if not block_ids:
        return "<span class=\"name\">0</span><span class=\"ocid\">No restored block volumes</span>"

    lines = []
    for index, volume_id in enumerate(block_ids):
        name = _indexed_value(block_names, index) or f"Restored block volume {index + 1}"
        lines.append(f"{name}: {volume_id}")
    return (
        f"<span class=\"name\">{len(block_ids)}</span>"
        f"<span class=\"ocid\">{escape('; '.join(str(line) for line in lines))}</span>"
    )


def _disk_count(result: dict[str, Any]) -> int:
    boot_count = 1 if result.get("boot_volume_id") else 0
    return boot_count + len(result.get("block_volume_ids") or [])


def _attached_disk_count(result: dict[str, Any]) -> int:
    boot_count = 1 if result.get("instance_id") and result.get("boot_volume_id") else 0
    return boot_count + len(result.get("volume_attachment_ids") or [])


def _indexed_value(values: list[Any], index: int) -> Any:
    return values[index] if index < len(values) else None


def _size_label(size_in_gbs: Any) -> str:
    if size_in_gbs is None or size_in_gbs == "":
        return "Not available"
    return f"{escape(str(size_in_gbs))} GB"


def _status_for_check(
    result: dict[str, Any],
    check_name: str,
    resource_id: Any = None,
) -> str:
    validation = result.get("validation")
    if validation is None:
        return "PENDING"

    checks = validation.get("checks") or []
    for check in checks:
        if check.get("name") != check_name:
            continue
        if resource_id is not None and check.get("resource_id") != resource_id:
            continue
        return "PASSED" if check.get("passed") else "FAILED"
    return "PENDING"


def _validation_passed(result: dict[str, Any]) -> bool | None:
    validation = result.get("validation")
    if validation is None:
        return None
    return bool(validation.get("passed"))


def _short(value: str) -> str:
    return value if len(value) <= 24 else f"...{value[-18:]}"
