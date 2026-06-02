# Добавление фоновой подложки к виджету OBS Overlay

Пошаговое руководство: как добавить переключаемую чёрную полупрозрачную подложку к любому виджету оверлея, по аналогии с тем, как это сделано для **Stats**.

---

## Обзор архитектуры

Подложка управляется CSS-переменной `--widget-bg-opacity`, которая передаётся через inline `style` элемента-обёртки. Значение хранится в конфиге (`config.json`) как поле `background_opacity` внутри объекта виджета.

```
config.json → gui_overlay.py (чекбокс) → config.py (сохранение) → overlay.js (рендер) → overlay.css (отображение)
```

---

## Файлы, которые нужно изменить

| Файл | Что делаем |
|---|---|
| `config.py` | Дефолтное значение `background_opacity` в конфиге виджета |
| `gui_overlay.py` | Чекбокс "Show background" в Widget Settings |
| `media/overlay/overlay.js` | Передача CSS-переменной в HTML |
| `media/overlay/overlay.css` | Стили подложки |

---

## Шаг 1: Конфиг (`config.py`)

В `DEFAULT_OVERLAY["widgets"]` у виджета уже есть поле `background_opacity`. Убедись что у целевого виджета оно присутствует:

```python
# config.py → DEFAULT_OVERLAY → widgets
{"id": "banishes", "enabled": False, "mode": "compact", "order": 80,
 "max_rows": 40, "background_opacity": 0.0, "show_border": False},
#                   ^^^^^^^^^^^^^^^^^^
#                   0.0 = подложка выключена по умолчанию
```

Это поле уже есть у всех виджетов. Ничего менять не нужно, если дефолт `0.0` устраивает.

---

## Шаг 2: GUI — чекбокс (`gui_overlay.py`)

В методе `open_overlay_widget_settings_dialog`, найди карточку нужного виджета и добавь чекбокс. Пример по аналогии со Stats:

### 2a. Создание чекбокса

```python
# Внутри карточки виджета (например, banishes_card)
widget_cfg = self._overlay_widget_config_by_id().get("banishes", {})
self.overlay_banishes_bg_checkbox = QCheckBox("Show background")
self.overlay_banishes_bg_checkbox.setChecked(float(widget_cfg.get("background_opacity", 0)) > 0)
self.overlay_banishes_bg_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
banishes_layout.addWidget(self.overlay_banishes_bg_checkbox)
```

### 2b. Сохранение значения

В методе `save_overlay_settings_from_ui`, добавь обработку чекбокса:

```python
# Внутри цикла for widget in overlay.get("widgets", []):
if widget_id == "banishes" and getattr(self, "overlay_banishes_bg_checkbox", None) is not None:
    widget = dict(widget)
    widget["background_opacity"] = 0.4 if self.overlay_banishes_bg_checkbox.isChecked() else 0.0
```

> **Значение 0.4** — стандартная прозрачность подложки, как у Stage Summary.

### 2c. Очистка ссылки при закрытии диалога

В методе `_clear_overlay_widget_settings_dialog_refs`:

```python
self.overlay_banishes_bg_checkbox = None
```

---

## Шаг 3: Рендер (`media/overlay/overlay.js`)

### Режим "мульти-виджет" (полный оверлей)

Если виджет уже рендерится через функцию `panel()` — **ничего делать не нужно**. Функция `panel()` автоматически читает `widget.background_opacity` и передаёт его в CSS:

```javascript
function panel(title, body, classes = "", widget = null) {
  const backgroundOpacity = clampNumber(widget?.background_opacity, 0, 1, ...);
  const style = `--widget-bg-opacity:${backgroundOpacity};...`;
  // ...
}
```

### Режим "одиночный виджет" (отдельный URL)

Если виджет в одиночном режиме рендерится **без** `panel()` (как Stats через `stats-widget-container`), нужно вручную пробросить CSS-переменную:

```javascript
case "banishes":
  if (requestedWidgetId() === "banishes") {
    const bgOpacity = clampNumber(widget?.background_opacity, 0, 1, 0.0);
    return `<div class="banishes-container" style="--widget-bg-opacity:${bgOpacity};">
      ${renderBanishes(state, widget)}
    </div>`;
  }
  return panel("Banishes", renderBanishes(state, widget), "wide banishes-widget", widget);
```

> **Примечание:** Большинство виджетов используют `panel()` в обоих режимах, поэтому этот шаг нужен только если виджет имеет специальный рендер для одиночного режима.

---

## Шаг 4: Стили (`media/overlay/overlay.css`)

### Подложка через panel (большинство виджетов)

Класс `.panel` уже поддерживает подложку:

```css
.panel {
  background: rgba(0, 0, 0, var(--widget-bg-opacity, var(--panel-bg-opacity)));
}
```

Поэтому для виджетов, которые рендерятся через `panel()`, **CSS менять не нужно**.

### Подложка для кастомного контейнера

Если виджет имеет свой контейнер (как `.stats-widget-container`), добавь:

```css
.my-widget-container {
  width: 100%;
  padding: calc(12px * var(--scale)) calc(16px * var(--scale));
  border-radius: 0;  /* острые углы */
  background: rgba(0, 0, 0, var(--widget-bg-opacity, 0));
}
```

### Фикс адаптивности для одиночного режима

Если контейнер содержит `auto-fit` грид, добавь правило для одиночного режима:

```css
.overlay-shell.single-widget .my-widget-container {
  width: calc(100vw - (16px * var(--scale)));
}
```

> **Почему это нужно:** Родитель `.overlay-shell.single-widget` имеет `width: fit-content`.
> Дочерний элемент с `width: 100%` создаёт циклическую зависимость — родитель подстраивается под контент, а контент — под родителя. Браузер разрешает это, схлопывая грид в одну колонку.
> Явная привязка к `100vw` (ширина OBS-источника) даёт гриду реальную ширину для расчёта колонок.

---

## Справка по значениям

| `background_opacity` | Результат |
|---|---|
| `0.0` | Полностью прозрачно (подложка выключена) |
| `0.2` | Лёгкая подложка |
| `0.4` | Стандартная подложка (как Stage Summary) |
| `0.6+` | Тяжёлая подложка (не рекомендуется) |

---

## Пример: как это выглядит для Stats

Реализация, на которую можно ориентироваться:

- **config.py** → строка с `"stats"` в `DEFAULT_OVERLAY["widgets"]` — поле `"background_opacity": 0.0`
- **gui_overlay.py** → `self.overlay_stats_bg_checkbox` — чекбокс в карточке Stats
- **overlay.js** → `case "stats"` → проброс `--widget-bg-opacity` в `stats-widget-container`
- **overlay.css** → `.stats-widget-container` и `.overlay-shell.single-widget .stats-widget-container`
