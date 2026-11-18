"""旧仪器数据校验：仅存每批失败项总数 fail_total 与部分单项 0/1 结果。

已知项与总数对不上（不存在任何 0/1 补全能同时满足已知项与总数）时拒收整批。
本模块只依赖标准库，便于离线单元测试。
"""
from itertools import combinations

from src.constants.assay import ITEMS, NAMES

FAIL_TOTAL_KEY = "fail_total"


def _is_missing(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def _parse_binary(value):
    """返回 (是否缺失, 0/1 或 None)；非 0/1 标记抛 ValueError。"""
    if _is_missing(value):
        return True, None
    if isinstance(value, bool):
        raise ValueError("不接受布尔标记")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("标记须为 0、1 或留空") from exc
    if number not in (0.0, 1.0):
        raise ValueError("检验标记仅接受 0(通过)、1(失败) 或留空(未知)")
    return False, int(number)


def _parse_total(value):
    if _is_missing(value):
        raise ValueError("旧仪器记录必须提供失败项总数 fail_total")
    if isinstance(value, bool):
        raise ValueError("失败项总数须为 0~5 的整数")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("失败项总数须为 0~5 的整数") from exc
    if not number.is_integer() or not 0 <= number <= len(ITEMS):
        raise ValueError("失败项总数须为 0~5 的整数")
    return int(number)


def normalize_legacy_records(records):
    """校验并规范化旧仪器记录。

    每行: {batch_id, fail_total, heat_fail?, ph_fail, ...}，单项可留空表示未知。
    任一单据不可行即抛 ValueError（含批次号与原因），全部通过才返回结构化结果。
    """
    if not isinstance(records, list) or not records:
        raise ValueError("旧仪器记录不能为空")
    normalized = []
    seen_ids = set()
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index + 1} 行不是有效记录对象")
        batch_id = raw.get("batch_id")
        if _is_missing(batch_id):
            raise ValueError(f"第 {index + 1} 行缺少批次号 batch_id")
        batch_id = str(batch_id).strip()
        if batch_id in seen_ids:
            raise ValueError(f"批次 {batch_id} 重复出现，每批仅允许一条记录")
        seen_ids.add(batch_id)
        try:
            total = _parse_total(raw.get(FAIL_TOTAL_KEY))
        except ValueError as exc:
            raise ValueError(f"批次 {batch_id}：{exc}") from exc
        known = {}
        unknown_keys = []
        for key in ITEMS:
            try:
                missing, bit = _parse_binary(raw.get(key))
            except ValueError as exc:
                raise ValueError(f"批次 {batch_id}：{NAMES[key]} {exc}") from exc
            if missing:
                unknown_keys.append(key)
            else:
                known[key] = bit
        if not known:
            raise ValueError(f"批次 {batch_id}：五项检验结果全部未知，至少需要一项已知结果")
        known_failures = sum(known.values())
        unknown_count = len(unknown_keys)
        if known_failures > total:
            raise ValueError(
                f"批次 {batch_id}：已知失败 {known_failures} 项已超过失败总数 {total}，数据对不上，拒收"
            )
        need_failures = total - known_failures
        if need_failures > unknown_count:
            raise ValueError(
                f"批次 {batch_id}：失败总数 {total} 要求未知项中至少 {need_failures} 项失败，"
                f"但未知项仅 {unknown_count} 项，数据对不上，拒收"
            )
        options = feasible_options(known, unknown_keys, need_failures)
        if not options:
            raise ValueError(f"批次 {batch_id}：不存在满足失败总数 {total} 的补全，拒收")
        row = {
            "batch_id": batch_id,
            FAIL_TOTAL_KEY: total,
            "known": known,
            "unknown_keys": unknown_keys,
            "need_failures": need_failures,
            "options": options,
        }
        normalized.append(row)
    return normalized


def feasible_options(known, unknown_keys, need_failures):
    """枚举一批未知项的全部可行 0/1 补全。

    返回 list[dict]，每个 dict 是 unknown_keys 上的一份完整赋值（0/1）。
    五项检验 => 未知项最多 4（至少一项已知）=> 最多 C(4, k) ≤ 6 种。
    """
    options = []
    for failed in combinations(unknown_keys, need_failures):
        assignment = {key: (1 if key in failed else 0) for key in unknown_keys}
        options.append(assignment)
    return options


def is_legacy_payload(records):
    """粗略识别一次导入是否为旧仪器格式（任一记录带 fail_total）。"""
    return isinstance(records, list) and any(
        isinstance(row, dict) and FAIL_TOTAL_KEY in row for row in records
    )


def completion_to_row(row, assignment):
    """把一份补全赋值还原为完整五项 0/1 记录（用于见证与核对）。"""
    values = dict(row["known"])
    values.update(assignment)
    return {"batch_id": row["batch_id"], **{key: values[key] for key in ITEMS}}


def partial_view(row):
    """接口/页面用的部分单项视图：未知项以 None 表示。"""
    values = {key: row["known"].get(key) for key in ITEMS}
    return {"batch_id": row["batch_id"], FAIL_TOTAL_KEY: row[FAIL_TOTAL_KEY], **values}
