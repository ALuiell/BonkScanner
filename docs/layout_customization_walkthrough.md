# Walkthrough: General Overlay Dynamic Layout Customization (Layout Editor Mode)

We have successfully implemented a fully customisable General Overlay layout engine. Users can now open the general overlay in a browser or OBS and visually drag and drop all 4 widgets to position them exactly as they wish.

---

## 📐 Dynamic Widget Stretching & Sizing

To make the stream HUD highly compact and tailored, users can now **stretch and resize widgets** individually in both width and height!

- **Native Resizing Handles**: In Layout Editor Mode (`?edit=true`), each widget features a native browser resize grip in the bottom-right corner.
- **Visual Column Reflow (Grid Reflow)**: Resizing widgets like **Stats** or **Banishes** horizontally instantly reorganises their elements! For example, stretching them wider automatically wraps them into **2, 3, or 4 columns**, dynamically optimizing screen real estate!
- **Resize and Drag Coexistence**: We implemented coordinate-based filters to ensure that clicking inside the bottom-right corner handles triggers resizing natively, while clicking anywhere else triggers smooth, physics-aware dragging.
- **Smart Debounced Persistence**: Dimensions are tracked using a high-performance JavaScript **`ResizeObserver`**. To ensure perfect page performance, resizing triggers are debounced by **500ms** so they only persist to `config.json` via a POST to `/api/save-widget-positions` once the user finishes stretching!
- **Unified Sizing Mappings**: Widths and heights are saved as absolute pixel values and applied cleanly in **both** absolute positioning mode and standard flow layouts.

---

## 🔍 Individual Widget Zoom & Dynamic Input scaling

In addition to custom coordinates and canvas resolution sizing, users can now **scale individual widgets** using both standard buttons and **direct text inputs**:

- **Interactive Hover Toolbar**: When hovering over any widget inside Layout Editor Mode (`?edit=true`), a sleek semi-transparent toolbar slides in at the top right showing:
  > **`[ - ]` `[ 100% ]` `[ + ]`**
- **Direct Scaling Inputs**: Instead of a static label, the percentage display is a fully interactive text input box!
  - **Quick Toggles**: Click `+` or `-` to scale the widget size up or down in steps of **5%** (clamped between `40%` and `400%`).
  - **Direct Numeric Typing**: Click on the percentage text box, type any custom integer scale you want (e.g. `85` or `125`), and press **Enter** or click away. The widget will instantly resize to exactly that scale and display `${value}%`!
- **CSS-Powered Layout Reflow**: Changing a widget's scale updates its local inline CSS variable `--scale` dynamically. Because the entire UI design uses calculations relative to `--scale`, the text size, padding, spacing, and inner columns all zoom **instantly and perfectly with zero latency**!
- **Unified Static & Absolute Layouts**: Widget-level scaling is supported in **both** visual editor mode and traditional flow mode!
- **Automatic Persistence**: Scaling a widget instantly triggers an asynchronous HTTP `POST` to `/api/save-widget-positions` to persist your individual widget scales inside `config.json`.

---

## 📸 Interactive In-Game HUD Preview

To make widget alignment completely effortless, the Layout Editor now integrates a **genius in-game screenshot backing preview**!

- **Live Game Backing**: In Layout Editor Mode (`?edit=true`), the canvas automatically loads a high-quality screenshot of the game's actual screen (`/assets/game_preview.jpg`).
- **Aspect-Ratio & Resolution Scaling**: We use CSS `background-size: 100% 100%;` to ensure that this preview screenshot dynamically and perfectly resizes to whatever resolution you enter in the control bar (whether it's `1920x1080`, `2560x1440`, or any other format).
- **Perfect HUD Mapping**: You can see exactly where the in-game minimap, health bars, and bottom status icons reside, allowing you to position `Stage Summary`, `Stats`, `Tracked Items`, and `Banishes` perfectly into the blank areas of the HUD.
- **Zero Impact on Streaming**: The background backing is exclusively rendered in Edit Mode inside your browser. When OBS loads the normal `/overlay` page, it remains 100% transparent and borderless.

---

## 🌟 Scalable & Customisable Canvas Resolution

To give you complete freedom, the layout engine is **fully scalable and customisable**! You can set your own custom canvas resolution directly from the editor:

- **Interactive Resolution Control Bar**: In Layout Editor Mode (`?edit=true`), a premium control bar is nested directly inside the top banner:
  > **Canvas Resolution: [ 1920 ] x [ 1080 ] [ Apply ]**
- **Instant Visual Feedback**: Changing the values and clicking **Apply** immediately resizes the dotted canvas boundary outline on your screen. Any future drags will automatically clamp within your custom resolution boundaries!
- **Automatic Persistence**: Clicking **Apply** triggers an asynchronous HTTP `POST` to `/api/save-canvas-resolution`, which permanently saves your custom dimensions (`canvas_width` and `canvas_height`) to your `config.json`.
- **OBS Sync**: When adding the Browser Source in OBS, simply specify the exact same custom Width and Height values you entered in the editor.

---

## Features Added

### 1. Visual Drag & Drop Layout Editor (Edit Mode)
- Accessing the overlay via `http://127.0.0.1:17845/overlay?edit=true` enables **Layout Editor Mode**.
- While in this mode, active polling is completely paused to prevent DOM recreation from resetting the drag states, ensuring 100% stable movement.
- Widgets are styled as modern glassmorphism draggable components with a beautiful dashed gold accent border on hover, indicating interactivity.

### 2. High-Fidelity Mock Data in Edit Mode
- If the game is not running or stats are unavailable, the editor automatically populates rich, premium mock data for all widgets (Stage Summary, Tracked Items, Stats, and Banishes) so you can see exactly how the layout looks when populated.

### 3. Sticky Glow Header Banner
- A sticky, semi-transparent dark banner appears at the top of the viewport during Edit Mode, displaying:
  > **Overlay Layout Editor**
  > Drag widgets to place them anywhere. Close this browser tab when done.

### 4. Direct Coordinates Persistence (Backend Sync)
- Moving a widget instantly fires an asynchronous HTTP `POST` request to `/api/save-widget-positions` with the exact `x` and `y` coordinates.
- The coordinates are saved permanently inside your `config.json` via python's `config.py` handler.
- If a widget doesn't have custom coordinates saved yet, it falls back to a smart, non-overlapping default layout grid (Stage Summary and Tracked Items on the left, Stats and Banishes on the far right) to guarantee clean first-time loads.

---

## Technical Details

### 💻 Frontend Assets
- **[media/overlay/overlay.js](file:///f:/Python/MegabonkReroll/media/overlay/overlay.js)**:
  - Added global `canvasWidth` and `canvasHeight` variables, dynamically synced with the server configuration state.
  - Implemented the banner resolution form and connected it to a POST endpoint `/api/save-canvas-resolution` to update and persist layout dimensions.
  - Bound the modern **Pointer Events** drag movement limits dynamically to these custom canvas variables.
  - Added individual scale zoom click event handlers (`decButtons` and `incButtons`).
  - Implemented text inputs focus/blur/blur-on-enter event handlers (`scaleInputs`) supporting direct percentage value entries.
  - Added **`ResizeObserver`** with a **500ms debounce** to capture and persist custom widget widths and heights dynamically.
- **[media/overlay/overlay.css](file:///f:/Python/MegabonkReroll/media/overlay/overlay.css)**:
  - Configured `.overlay-shell.absolute-layout` to read dimensions dynamically via CSS variables `--canvas-width` and `--canvas-height`.
  - Added style rules for `.edit-resolution-controls` (Outfit typography, dark input fields, glowing focus state, and gold accent apply button).
  - Applied the `/assets/game_preview.jpg` background style inside the Edit Mode canvas with 100% automated scaling.
  - Added `.widget-toolbar` and `.widget-scale-input` styles supporting dynamic scale text inputs with sleek border focus glow animations.
  - Added native `resize: both; overflow: hidden;` rules for `.widget-wrapper.draggable` and flex alignment inside `.panel` to expand perfectly.

### ⚙️ Python Backend
- **[overlay_server.py](file:///f:/Python/MegabonkReroll/overlay_server.py)**:
  - Added a new `/api/save-canvas-resolution` POST handler to persist custom width and height.
  - Updated `/api/save-widget-positions` to safely receive and update individual `"scale"`, `"width"`, and `"height"` parameters inside raw JSON payloads without touching coordinates.
- **[config.py](file:///f:/Python/MegabonkReroll/config.py)**: Declared default resolution parameters in `DEFAULT_OVERLAY` and coerced them in `normalize_overlay_config`.
- **[overlay_state.py](file:///f:/Python/MegabonkReroll/overlay_state.py)**: Included `canvas_width`, `canvas_height`, individual widget scales, widths, and heights in `/api/overlay-state` response.

---

## How to use

1. **Enter Editor Mode**:
   Open **[http://127.0.0.1:17845/overlay?edit=true](http://127.0.0.1:17845/overlay?edit=true)** in your web browser.
2. **Set Custom Resolution**:
   In the resolution control bar at the top, enter your preferred width and height (e.g. `2560` x `1440` for 2K, or `1280` x `720` for 720p) and click **Apply**.
3. **Arrange, Scale & Resize Widgets**:
   - Drag any widget to position it where you want on the canvas.
   - Hover over any widget to reveal the scale toolbar. Click `+` or `-` to zoom, or **click directly on the percentage text box, type any percentage** (e.g. `125`), and press **Enter** to instantly resize.
   - **Resize manually**: Hover over the bottom-right corner of any widget and drag the resize handle to dynamically stretch its width and height. Resizing a widget horizontally automatically wraps its inner elements into multiple columns!
4. **Lock Layout**:
   Once you are happy, close the editor browser tab. The saved layout is now applied borderless and locked at **[http://127.0.0.1:17845/overlay](http://127.0.0.1:17845/overlay)**.
5. **Set Up OBS**:
   Add a Browser Source in OBS, paste `http://127.0.0.1:17845/overlay` (or a specific widget link like `http://127.0.0.1:17845/overlay/stats`), and set **Width** and **Height** to match your preferences (or match the custom width/height values you set for that widget).

   > [!IMPORTANT]
   > **OBS Cache Refresh Required**:
   > Because OBS aggressively caches static scripts (`overlay.js`) and stylesheets (`overlay.css`), any newly added layout rules or size configurations won't render inside OBS until the cache is cleared!
   > 
   > To clear the cache and force OBS to load the new sizing:
   > 1. Right-click your **Browser Source** in OBS and select **Properties**.
   > 2. Scroll down in the Properties window.
   > 3. Click the **"Refresh cache of current page"** button.
   > 4. Click **OK**.
   > 
   > This instantly forces OBS to reload the assets, immediately locking the widgets at your custom-tailored dimensions with responsive column reflow fully active!
