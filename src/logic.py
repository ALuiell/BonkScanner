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
    microwaves = score_microwaves(stats)

    boss = stats.get("Boss Curses", 0)
    
    weights = scores_config.get("weights", {})
    w_moai = weights.get("moais", 3.0)
    w_shady = weights.get("shady", 2.0)
    w_boss = weights.get("boss", 1.0)
    w_magnet = weights.get("magnet", 0.5)
    
    multipliers = scores_config.get("multipliers", {}).get("microwave", {})
    m_1 = multipliers.get("1", 1.0)
    m_2 = multipliers.get("2", 1.25)
    
    multiplier = m_2 if microwaves >= 2 else m_1
    
    base_score = (moai * w_moai) + (shady * w_shady) + (boss * w_boss) + (min(magnet, 2) * w_magnet)
    return base_score * multiplier

def evaluate_map_by_scores(stats: dict, scores_config: dict) -> dict | None:
    """Оценивает карту по системе Scores и возвращает уровень качества (как шаблон), если она прошла порог."""
    score = calculate_score(stats, scores_config)
    
    thresholds = scores_config.get("thresholds", {})
    active_tiers = scores_config.get("active_tiers", [])
    
    shady = stats.get("Shady Guy", 0)
    moai = stats.get("Moais", 0)
    sm_total = shady + moai
    microwaves = score_microwaves(stats)

    boss = stats.get("Boss Curses", 0)

    # Определяем наивысший достигнутый тир
    achieved_tier = None
    
    # Проверка Perfect+
    if "Perfect+" in active_tiers and score >= thresholds.get("Perfect+", 30.0):
        if microwaves >= 2:
            achieved_tier = "Perfect+"
            
    # Проверка Perfect
    if not achieved_tier and "Perfect" in active_tiers and score >= thresholds.get("Perfect", 25.0):
        if microwaves >= 2 or (microwaves == 1 and sm_total >= 8 and boss >= 2):
            achieved_tier = "Perfect"
            
    # Проверка Good
    if not achieved_tier and "Good" in active_tiers and score >= thresholds.get("Good", 20.0):
        achieved_tier = "Good"
        
    # Проверка Light
    if not achieved_tier and "Light" in active_tiers and score >= thresholds.get("Light", 14.0):
        achieved_tier = "Light"
        
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
            "color": colors.get(achieved_tier, "BLUE"),
            "score": score
        }
        
    return None

def find_matching_template(
    stats: dict,
    active_names: list,
    all_templates: list,
    context: dict | None = None,
) -> dict | None:
    """Return the first active template matched by the provided stats."""
    shady = stats.get("Shady Guy", 0)
    moai = stats.get("Moais", 0)
    microwaves = template_microwaves(stats)

    boss = stats.get("Boss Curses", 0)
    bald_heads = stats.get("Bald Heads", 0)
    sm_total = shady + moai

    sorted_templates = sorted(all_templates, key=lambda t: t.get("id", 0), reverse=True)

    for template in sorted_templates:
        if template.get("name") not in active_names:
            continue

        meets_conditions = True

        if "sm_total" in template and sm_total < template["sm_total"]:
            meets_conditions = False
        if "shady" in template and shady < template["shady"]:
            meets_conditions = False
        if "moai" in template and moai < template["moai"]:
            meets_conditions = False
        if "micro" in template and microwaves < template["micro"]:
            meets_conditions = False
        if "boss" in template and boss < template["boss"]:
            meets_conditions = False
        if "bald_heads" in template and template["bald_heads"] > 0:
            if not supports_bald_heads(stats, context) or bald_heads < template["bald_heads"]:
                meets_conditions = False

        if meets_conditions:
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