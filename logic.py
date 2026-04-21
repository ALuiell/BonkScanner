import os
import datetime

def calculate_score(stats: dict, scores_config: dict) -> float:
    """Вычисляет балл карты на основе системы Scores."""
    shady = stats.get("Shady Guy", 0)
    moai = stats.get("Moais", 0)
    magnet = stats.get("Magnet Shrines", 0)
    
    microwaves = stats.get("Microwaves", 1)
    if microwaves < 1:
        microwaves = 1
    elif microwaves > 2:
        microwaves = 2

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
    
    microwaves = stats.get("Microwaves", 1)
    if microwaves < 1: microwaves = 1
    elif microwaves > 2: microwaves = 2
        
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

def find_matching_template(stats: dict, active_names: list, all_templates: list) -> dict | None:
    """Return the first active template matched by the provided stats."""
    shady = stats.get("Shady Guy", 0)
    moai = stats.get("Moais", 0)
    
    microwaves = stats.get("Microwaves", 1)
    if microwaves < 1:
        microwaves = 1
    elif microwaves > 2:
        microwaves = 2

    boss = stats.get("Boss Curses", 0)
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

        if meets_conditions:
            return template

    return None

def conditions_met(stats: dict, active_names: list, all_templates: list) -> bool:
    """Check map against active profiles dynamically."""
    template = find_matching_template(stats, active_names, all_templates)
    if template is None:
        return False
    return True
