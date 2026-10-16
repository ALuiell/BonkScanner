from core.template_colors import DEFAULT_TEMPLATE_COLOR
from core.template_conditions import (
    TEMPLATE_COUNTERS,
    condition_maximum,
    condition_minimum,
)


SCORE_TIER_ORDER = ("Light", "Good", "Perfect", "Perfect+")
SCORE_TIER_EVALUATION_ORDER = tuple(reversed(SCORE_TIER_ORDER))
SCORE_TIER_DEFAULT_THRESHOLDS = {
    "Light": 14.0,
    "Good": 20.0,
    "Perfect": 25.0,
    "Perfect+": 30.0,
}


def normalize_microwaves(value: int | None) -> int:
    if value is None or value < 1:
        return 1
    if value > 2:
        return 2
    return value


def raw_microwaves(value: int | None) -> int:
    if value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def is_high_total_chest_family(stats: dict) -> bool:
    chests = stats.get("Chests", 0)
    return isinstance(chests, (int, float)) and chests >= 69


def template_microwaves(stats: dict) -> int:
    value = stats.get("Microwaves")
    if is_high_total_chest_family(stats):
        return raw_microwaves(value)
    return normalize_microwaves(value)


def score_microwaves(stats: dict) -> int:
    # Score mode intentionally keeps the legacy OCR-era 1..2 microwave
    # buckets so existing score tiers continue to behave as before.
    return normalize_microwaves(stats.get("Microwaves"))


def supports_bald_heads(stats: dict, context: dict | None = None) -> bool:
    if is_high_total_chest_family(stats):
        return True
    return bool(context and context.get("supports_bald_heads"))


def calculate_score(stats: dict, scores_config: dict) -> float:
    """Вычисляет балл карты на основе системы Scores."""
    shady = stats.get("Shady Guy", 0)
    moai = stats.get("Moais", 0)
    magnet = stats.get("Magnet Shrines", 0)
    challenges = stats.get("Challenges", 0)
    microwaves = score_microwaves(stats)

    boss = stats.get("Boss Curses", 0)
    
    weights = scores_config.get("weights", {})
    w_moai = weights.get("moais", 3.0)
    w_shady = weights.get("shady", 2.0)
    w_boss = weights.get("boss", 1.0)
    w_magnet = weights.get("magnet", 0.5)
    w_challenges = weights.get("challenges", 0.0)
    
    multipliers = scores_config.get("multipliers", {}).get("microwave", {})
    m_1 = multipliers.get("1", 1.0)
    m_2 = multipliers.get("2", 1.25)
    
    multiplier = m_2 if microwaves >= 2 else m_1
    
    base_score = (
        (moai * w_moai)
        + (shady * w_shady)
        + (boss * w_boss)
        + (magnet * w_magnet)
        + (challenges * w_challenges)
    )
    return base_score * multiplier


def score_tier_miss_reasons(
    stats: dict,
    scores_config: dict,
    tier: str,
    *,
    score: float | None = None,
) -> tuple[str, ...]:
    """Explain every unmet condition for one score tier.

    This is also the predicate used by :func:`evaluate_map_by_scores`, so the
    scanner cannot claim a missing condition that its actual stop decision did
    not require.
    """
    if score is None:
        score = calculate_score(stats, scores_config)
    score = float(score)
    try:
        threshold = float(
            scores_config.get("thresholds", {}).get(
                tier,
                SCORE_TIER_DEFAULT_THRESHOLDS.get(tier, 0.0),
            )
        )
    except (TypeError, ValueError):
        threshold = 0.0

    reasons: list[str] = []
    if score < threshold:
        reasons.append(
            f"Score {score:.1f}/{threshold:.1f} (−{threshold - score:.1f})"
        )

    shady = int(stats.get("Shady Guy", 0) or 0)
    moai = int(stats.get("Moais", 0) or 0)
    boss = int(stats.get("Boss Curses", 0) or 0)
    microwaves = score_microwaves(stats)

    if tier == "Perfect+" and microwaves < 2:
        reasons.append(f"Microwaves {microwaves}/2")
    elif tier == "Perfect" and microwaves < 2:
        sm_total = shady + moai
        if sm_total < 8:
            reasons.append(f"S+M {sm_total}/8")
        if boss < 2:
            reasons.append(f"Boss {boss}/2")

    return tuple(reasons)


def evaluate_map_by_scores(stats: dict, scores_config: dict) -> dict | None:
    """Оценивает карту по системе Scores и возвращает уровень качества (как шаблон), если она прошла порог."""
    score = calculate_score(stats, scores_config)
    active_tiers = scores_config.get("active_tiers", [])
    achieved_tier = next(
        (
            tier
            for tier in SCORE_TIER_EVALUATION_ORDER
            if tier in active_tiers
            and not score_tier_miss_reasons(
                stats,
                scores_config,
                tier,
                score=score,
            )
        ),
        None,
    )
        
    if achieved_tier:
        # Возвращаем "фейковый" шаблон для совместимости с GUI
        colors = {
            "Light": "WHITE",
            "Good": "GREEN",
            "Perfect": "YELLOW",
            "Perfect+": "LIGHTRED_EX"
        }
        return {
            "name": achieved_tier,
            "color": colors.get(achieved_tier, DEFAULT_TEMPLATE_COLOR),
            "score": score
        }
        
    return None


def template_miss_reasons(
    stats: dict,
    template: dict,
    context: dict | None = None,
) -> tuple[str, ...]:
    """Explain the exact template bounds that ``stats`` does not satisfy."""
    shady = int(stats.get("Shady Guy", 0) or 0)
    moai = int(stats.get("Moais", 0) or 0)
    counter_values = {
        "shady": shady,
        "moai": moai,
        "micro": int(template_microwaves(stats) or 0),
        "boss": int(stats.get("Boss Curses", 0) or 0),
        "magnet": int(stats.get("Magnet Shrines", 0) or 0),
        "challenges": int(stats.get("Challenges", 0) or 0),
        "bald_heads": int(stats.get("Bald Heads", 0) or 0),
    }
    reasons: list[str] = []

    if "sm_total" in template:
        try:
            sm_minimum = max(0, int(template.get("sm_total", 0) or 0))
        except (TypeError, ValueError):
            sm_minimum = 0
        sm_total = shady + moai
        if sm_total < sm_minimum:
            reasons.append(f"S+M {sm_total}/{sm_minimum}")

    for counter in TEMPLATE_COUNTERS:
        value = counter_values[counter.key]
        minimum = condition_minimum(template, counter.key)
        maximum = condition_maximum(template, counter.key)
        if counter.key == "bald_heads" and minimum > 0:
            if not supports_bald_heads(stats, context):
                reasons.append(f"{counter.label} unavailable")
            elif value < minimum:
                reasons.append(f"{counter.label} {value}/{minimum}")
        elif value < minimum:
            reasons.append(f"{counter.label} {value}/{minimum}")
        if maximum is not None and value > maximum:
            reasons.append(f"{counter.label} {value} (needs ≤{maximum})")

    return tuple(reasons)


def find_matching_template(
    stats: dict,
    active_names: list,
    all_templates: list,
    context: dict | None = None,
) -> dict | None:
    """Return the first active template matched by the provided stats."""
    sorted_templates = sorted(all_templates, key=lambda t: t.get("id", 0), reverse=True)

    for template in sorted_templates:
        if template.get("name") not in active_names:
            continue
        if not template_miss_reasons(stats, template, context=context):
            return template

    return None

def conditions_met(
    stats: dict,
    active_names: list,
    all_templates: list,
    context: dict | None = None,
) -> bool:
    """Check map against active profiles dynamically."""
    template = find_matching_template(stats, active_names, all_templates, context=context)
    if template is None:
        return False
    return True
