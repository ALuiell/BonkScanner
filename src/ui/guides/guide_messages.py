"""Translations for the native Quick Guides."""

# Topic rows: menu, title, summary, footnote, action. Game terms are supplied
# separately by the application's game localization service.
_TOPIC_FIELDS = ("menu", "title", "summary", "footnote", "action")
_TOPICS = {
    "en": {
        "welcome": ("Quick start", "What would you like to do?", "Find a map, review a run, or show stats over the game.", "Open this guide again from the top bar.", "Find a map"),
        "restart": ("Map Search", "Find the map you want", "Choose Templates or Scores, then press Start to search.", "Recommended hold time: 0.01 s threshold + 0.05 s margin = 0.06 s.", "Open Restart"),
        "live": ("Live Stats", "Follow your current run", "See how lucky your drops were and where your stat bonuses came from.", "", "Open Live"),
        "recordings": ("Recordings", "Review a saved run", "Jump to a saved moment, compare two points or check where your damage came from.", "", "Open Recordings"),
        "obs": ("OBS", "Edit your OBS layout", "Open the browser layout editor. Drag to move, resize, and rearrange widgets.", "Copy the browser-source URL into OBS.", "Open layout editor"),
        "game_overlay": ("Game Overlay", "See data over your game", "Show Full Map markers, active powerups, and Luck over the game.", "Arrange the widgets in Game Overlay.", "Open Game Overlay"),
        "premium": ("Overview", "What Premium includes", "Choose a feature to see an example.", "One supporter key activates all Premium features.", "How to get Premium"),
        "minimap": ("Minimap markers", "Keep markers in view", "Show marked objects on the minimap during a run.", "Manual markers on the Full Map are free.", "Get Premium"),
        "stock": ("Shop memory", "Remember Shady Guy's stock", "See items and prices from your last visit to each shop on the Full Map.", "Visit the shop again to update its stock.", "Get Premium"),
        "shady": ("Shady Guy Analytics", "Compare merchant offers", "Review the items offered by shops you visited.", "Saved history remains available without Premium.", "Get Premium"),
        "roll": ("Roll Analytics", "Review Dice and Chaos rolls", "Review saved Dice passive and Chaos Tome roll history.", "Saved history and recording data remain available without Premium.", "Get Premium"),
        "access": ("Activate a key", "One key for Premium", "Support the project, then enter your personal key in Support and press Activate.", "Auto-Reroll, Live, recordings, and basic overlays are free.", "Open Support"),
    },
    "ru": {
        "welcome": ("Быстрый старт", "Что вы хотите сделать?", "Найдите карту, изучите забег или выведите статистику поверх игры.", "Откройте гид снова на верхней панели.", "Найти карту"),
        "restart": ("Поиск карты", "Найдите нужную карту", "Выберите Templates или Scores и нажмите Start для поиска.", "Рекомендуемое удержание: 0,01 с порог + 0,05 с запас = 0,06 с.", "Открыть Restart"),
        "live": ("Статистика Live", "Следите за текущим забегом", "Смотрите, насколько повезло с добычей и откуда взялись бонусы к характеристикам.", "", "Открыть Live"),
        "recordings": ("Записи", "Разберите сохранённый забег", "Перейдите к нужному моменту, сравните две точки или посмотрите, что нанесло больше всего урона.", "", "Открыть записи"),
        "obs": ("OBS", "Измените раскладку OBS", "Откройте редактор в браузере. Перетаскивайте виджеты, меняйте их размеры и расположение.", "Скопируйте URL браузерного источника в OBS.", "Открыть редактор"),
        "game_overlay": ("Game Overlay", "Данные поверх игры", "Показывайте метки Full Map, активные усиления и Luck поверх игры.", "Разместите виджеты в Game Overlay.", "Открыть Game Overlay"),
        "premium": ("Обзор", "Возможности Premium", "Выберите функцию, чтобы посмотреть пример.", "Один ключ поддержки открывает все функции Premium.", "Как получить Premium"),
        "minimap": ("Метки на миникарте", "Следите за метками", "Показывайте отмеченные объекты на миникарте во время забега.", "Ручные метки на Full Map доступны бесплатно.", "Получить Premium"),
        "stock": ("Память магазина", "Вспомните товары Shady Guy", "Смотрите товары и цены с последнего визита к каждому продавцу на Full Map.", "Зайдите снова, чтобы обновить ассортимент.", "Получить Premium"),
        "shady": ("Shady Guy Analytics", "Сравните предложения", "Изучайте товары посещённых магазинов.", "Сохранённая история доступна без Premium.", "Получить Premium"),
        "roll": ("Roll Analytics", "Изучите выпадения Dice и Chaos", "Просматривайте сохранённую историю Dice passive и Chaos Tome.", "Сохранённая история и данные записей доступны без Premium.", "Получить Premium"),
        "access": ("Активация ключа", "Один ключ для Premium", "Поддержите проект, затем вставьте личный ключ в Support и нажмите Activate.", "Auto-Reroll, Live, записи и основные оверлеи бесплатны.", "Открыть Support"),
    },
    "uk": {
        "welcome": ("Швидкий старт", "Що ви хочете зробити?", "Знайдіть мапу, перегляньте забіг або виведіть статистику поверх гри.", "Відкрийте гід знову на верхній панелі.", "Знайти мапу"),
        "restart": ("Пошук мапи", "Знайдіть потрібну мапу", "Оберіть Templates або Scores і натисніть Start для пошуку.", "Рекомендоване утримання: 0,01 с поріг + 0,05 с запас = 0,06 с.", "Відкрити Restart"),
        "live": ("Статистика наживо", "Стежте за поточним забігом", "Дивіться, наскільки пощастило зі здобиччю і звідки взялися бонуси до характеристик.", "", "Відкрити Live"),
        "recordings": ("Записи", "Перегляньте збережений забіг", "Перейдіть до потрібного моменту, порівняйте дві точки або перегляньте джерела шкоди.", "", "Відкрити записи"),
        "obs": ("OBS", "Змініть розкладку OBS", "Відкрийте редактор у браузері. Перетягуйте віджети, змінюйте їхні розміри та розташування.", "Скопіюйте URL джерела браузера в OBS.", "Відкрити редактор"),
        "game_overlay": ("Game Overlay", "Дані поверх гри", "Показуйте мітки Full Map, активні підсилення та Luck поверх гри.", "Розташуйте віджети в Game Overlay.", "Відкрити Game Overlay"),
        "premium": ("Огляд", "Можливості Premium", "Оберіть функцію, щоб переглянути приклад.", "Один ключ підтримки відкриває всі функції Premium.", "Як отримати Premium"),
        "minimap": ("Мітки на мінімапі", "Стежте за мітками", "Показуйте позначені об'єкти на мінімапі під час забігу.", "Ручні мітки на Full Map доступні безкоштовно.", "Отримати Premium"),
        "stock": ("Пам'ять магазину", "Згадайте товари Shady Guy", "Переглядайте товари й ціни з останнього візиту до кожного продавця на Full Map.", "Зайдіть знову, щоб оновити асортимент.", "Отримати Premium"),
        "shady": ("Shady Guy Analytics", "Порівняйте пропозиції", "Переглядайте товари відвіданих магазинів.", "Збережена історія доступна без Premium.", "Отримати Premium"),
        "roll": ("Roll Analytics", "Перегляньте випадіння Dice і Chaos", "Переглядайте збережену історію Dice passive і Chaos Tome.", "Збережена історія та дані записів доступні без Premium.", "Отримати Premium"),
        "access": ("Активація ключа", "Один ключ для Premium", "Підтримайте проєкт, вставте особистий ключ у Support і натисніть Activate.", "Auto-Reroll, Live, записи та основні оверлеї безкоштовні.", "Відкрити Support"),
    },
    "de": {
        "welcome": ("Schnellstart", "Was möchtest du tun?", "Finde eine Karte, sieh einen Lauf an oder zeige Werte im Spiel.", "Öffne diesen Guide erneut über die obere Leiste.", "Karte finden"),
        "restart": ("Kartensuche", "Finde deine Karte", "Wähle Templates oder Scores und drücke Start für die Suche.", "Empfohlene Haltedauer: 0,01 s Schwelle + 0,05 s Reserve = 0,06 s.", "Restart öffnen"),
        "live": ("Live-Statistik", "Verfolge deinen aktuellen Lauf", "Sieh, wie viel Glück du bei der Beute hattest und woher deine Werteboni kommen.", "", "Live öffnen"),
        "recordings": ("Aufnahmen", "Sieh dir einen gespeicherten Lauf an", "Springe zu einem Zeitpunkt, vergleiche zwei Punkte oder prüfe die Schadensquellen.", "", "Aufnahmen öffnen"),
        "obs": ("OBS", "OBS-Layout bearbeiten", "Öffne den Browser-Layouteditor. Verschiebe und ordne Widgets per Ziehen an und ändere ihre Größe.", "Kopiere die Browserquellen-URL in OBS.", "Layouteditor öffnen"),
        "game_overlay": ("Game Overlay", "Daten im Spiel sehen", "Zeige Full-Map-Markierungen, aktive Powerups und Luck über dem Spiel.", "Ordne Widgets im Game Overlay an.", "Game Overlay öffnen"),
        "premium": ("Übersicht", "Das bietet Premium", "Wähle eine Funktion, um ein Beispiel zu sehen.", "Ein Supporter-Schlüssel schaltet alle Premium-Funktionen frei.", "So erhältst du Premium"),
        "minimap": ("Minimap-Markierungen", "Markierungen im Blick", "Zeige markierte Objekte während des Laufs auf der Minimap.", "Manuelle Markierungen auf der Full Map sind kostenlos.", "Premium erhalten"),
        "stock": ("Shop-Gedächtnis", "Shady Guys Angebot merken", "Sieh Artikel und Preise des letzten Besuchs jedes Händlers auf der Full Map.", "Besuche den Shop erneut, um das Angebot zu aktualisieren.", "Premium erhalten"),
        "shady": ("Shady Guy Analytics", "Händlerangebote vergleichen", "Sieh die Angebote besuchter Shops an.", "Gespeicherte Historie bleibt ohne Premium verfügbar.", "Premium erhalten"),
        "roll": ("Roll Analytics", "Dice- und Chaos-Würfe ansehen", "Sieh die gespeicherte Historie von Dice passive und Chaos Tome an.", "Gespeicherte Historie und Aufnahmedaten bleiben ohne Premium verfügbar.", "Premium erhalten"),
        "access": ("Schlüssel aktivieren", "Ein Schlüssel für Premium", "Unterstütze das Projekt und gib deinen persönlichen Schlüssel unter Support ein; drücke Activate.", "Auto-Reroll, Live, Aufnahmen und grundlegende Overlays sind kostenlos.", "Support öffnen"),
    },
    "fr": {
        "welcome": ("Démarrage rapide", "Que voulez-vous faire ?", "Trouvez une carte, consultez une partie ou affichez les stats sur le jeu.", "Rouvrez ce guide depuis la barre supérieure.", "Trouver une carte"),
        "restart": ("Recherche de carte", "Trouvez votre carte", "Choisissez Templates ou Scores, puis appuyez sur Start pour lancer la recherche.", "Maintien recommandé : 0,01 s de seuil + 0,05 s de marge = 0,06 s.", "Ouvrir Restart"),
        "live": ("Stats en direct", "Suivez votre partie en cours", "Voyez si la chance vous a souri côté butin et d’où viennent vos bonus de stats.", "", "Ouvrir Live"),
        "recordings": ("Enregistrements", "Revoyez une partie enregistrée", "Accédez à un moment sauvegardé, comparez deux points ou consultez les sources de dégâts.", "", "Ouvrir les enregistrements"),
        "obs": ("OBS", "Modifier la disposition OBS", "Ouvrez l'éditeur de disposition dans le navigateur. Déplacez, redimensionnez et réorganisez les widgets par glisser-déposer.", "Copiez l'URL de la source navigateur dans OBS.", "Ouvrir l'éditeur"),
        "game_overlay": ("Game Overlay", "Voir les données sur le jeu", "Affichez les marqueurs Full Map, les bonus actifs et Luck sur le jeu.", "Disposez les widgets dans Game Overlay.", "Ouvrir Game Overlay"),
        "premium": ("Aperçu", "Les fonctions Premium", "Choisissez une fonction pour voir un exemple.", "Une clé de soutien active toutes les fonctions Premium.", "Comment obtenir Premium"),
        "minimap": ("Marqueurs de minicarte", "Gardez les marqueurs en vue", "Affichez les objets marqués sur la minicarte pendant la partie.", "Les marqueurs manuels sur la Full Map sont gratuits.", "Obtenir Premium"),
        "stock": ("Mémoire des boutiques", "Retrouvez le stock de Shady Guy", "Voyez les objets et prix de votre dernière visite à chaque boutique sur la Full Map.", "Revenez à la boutique pour actualiser son stock.", "Obtenir Premium"),
        "shady": ("Shady Guy Analytics", "Comparez les offres", "Consultez les objets proposés par les boutiques visitées.", "L'historique sauvegardé reste accessible sans Premium.", "Obtenir Premium"),
        "roll": ("Roll Analytics", "Consultez les tirages Dice et Chaos", "Consultez l'historique sauvegardé de Dice passive et Chaos Tome.", "L'historique et les données des enregistrements restent accessibles sans Premium.", "Obtenir Premium"),
        "access": ("Activer une clé", "Une clé pour Premium", "Soutenez le projet, puis saisissez votre clé personnelle dans Support et appuyez sur Activate.", "Auto-Reroll, Live, les enregistrements et les overlays de base sont gratuits.", "Ouvrir Support"),
    },
    "es": {
        "welcome": ("Inicio rápido", "¿Qué quieres hacer?", "Encuentra un mapa, revisa una partida o muestra estadísticas sobre el juego.", "Vuelve a abrir esta guía desde la barra superior.", "Buscar un mapa"),
        "restart": ("Búsqueda de mapa", "Encuentra tu mapa", "Elige Templates o Scores y pulsa Start para buscar.", "Pulsación recomendada: 0,01 s de umbral + 0,05 s de margen = 0,06 s.", "Abrir Restart"),
        "live": ("Estadísticas en directo", "Sigue tu partida actual", "Mira cuánta suerte tuviste con el botín y de dónde vienen tus bonificaciones de estadísticas.", "", "Abrir Live"),
        "recordings": ("Grabaciones", "Revisa una partida guardada", "Salta a un momento guardado, compara dos puntos o consulta las fuentes de daño.", "", "Abrir grabaciones"),
        "obs": ("OBS", "Edita el diseño de OBS", "Abre el editor de diseño en el navegador. Arrastra para mover, redimensionar y reorganizar widgets.", "Copia la URL de la fuente de navegador en OBS.", "Abrir editor de diseño"),
        "game_overlay": ("Game Overlay", "Datos sobre el juego", "Muestra los marcadores de Full Map, mejoras activas y Luck sobre el juego.", "Organiza los widgets en Game Overlay.", "Abrir Game Overlay"),
        "premium": ("Resumen", "Qué incluye Premium", "Elige una función para ver un ejemplo.", "Una clave de apoyo activa todas las funciones Premium.", "Cómo obtener Premium"),
        "minimap": ("Marcadores del minimapa", "Ten los marcadores a la vista", "Muestra los objetos marcados en el minimapa durante la partida.", "Los marcadores manuales en Full Map son gratuitos.", "Obtener Premium"),
        "stock": ("Memoria de tienda", "Recuerda el inventario de Shady Guy", "Consulta en Full Map los objetos y precios de tu última visita a cada tienda.", "Vuelve a la tienda para actualizar su inventario.", "Obtener Premium"),
        "shady": ("Shady Guy Analytics", "Compara ofertas", "Consulta los objetos ofrecidos por las tiendas visitadas.", "El historial guardado sigue disponible sin Premium.", "Obtener Premium"),
        "roll": ("Roll Analytics", "Revisa las tiradas de Dice y Chaos", "Consulta el historial guardado de Dice passive y Chaos Tome.", "El historial y los datos de grabaciones siguen disponibles sin Premium.", "Obtener Premium"),
        "access": ("Activar clave", "Una clave para Premium", "Apoya el proyecto, introduce tu clave personal en Support y pulsa Activate.", "Auto-Reroll, Live, grabaciones y superposiciones básicas son gratuitos.", "Abrir Support"),
    },
    "pt": {
        "welcome": ("Início rápido", "O que você quer fazer?", "Encontre um mapa, reveja uma partida ou mostre estatísticas sobre o jogo.", "Abra este guia novamente pela barra superior.", "Encontrar mapa"),
        "restart": ("Busca de mapa", "Encontre seu mapa", "Escolha Templates ou Scores e pressione Start para buscar.", "Tempo recomendado: 0,01 s de limite + 0,05 s de margem = 0,06 s.", "Abrir Restart"),
        "live": ("Estatísticas ao vivo", "Acompanhe sua partida atual", "Veja quanta sorte teve com o saque e de onde vieram os bônus de atributos.", "", "Abrir Live"),
        "recordings": ("Gravações", "Reveja uma partida salva", "Vá até um momento salvo, compare dois pontos ou confira as fontes de dano.", "", "Abrir gravações"),
        "obs": ("OBS", "Edite o layout do OBS", "Abra o editor de layout no navegador. Arraste para mover, redimensionar e reorganizar os widgets.", "Copie a URL da fonte de navegador para o OBS.", "Abrir editor de layout"),
        "game_overlay": ("Game Overlay", "Dados sobre o jogo", "Mostre marcadores do Full Map, melhorias ativas e Luck sobre o jogo.", "Organize os widgets no Game Overlay.", "Abrir Game Overlay"),
        "premium": ("Visão geral", "O que o Premium inclui", "Escolha um recurso para ver um exemplo.", "Uma chave de apoiador ativa todos os recursos Premium.", "Como obter Premium"),
        "minimap": ("Marcadores no minimapa", "Mantenha os marcadores à vista", "Mostre objetos marcados no minimapa durante a partida.", "Marcadores manuais no Full Map são gratuitos.", "Obter Premium"),
        "stock": ("Memória da loja", "Lembre o estoque do Shady Guy", "Veja no Full Map os itens e preços da última visita a cada loja.", "Visite a loja novamente para atualizar o estoque.", "Obter Premium"),
        "shady": ("Shady Guy Analytics", "Compare ofertas", "Veja os itens oferecidos pelas lojas visitadas.", "O histórico salvo continua disponível sem Premium.", "Obter Premium"),
        "roll": ("Roll Analytics", "Veja os sorteios de Dice e Chaos", "Veja o histórico salvo de Dice passive e Chaos Tome.", "O histórico e os dados das gravações continuam disponíveis sem Premium.", "Obter Premium"),
        "access": ("Ativar chave", "Uma chave para Premium", "Apoie o projeto, insira sua chave pessoal em Support e pressione Activate.", "Auto-Reroll, Live, gravações e overlays básicos são gratuitos.", "Abrir Support"),
    },
}

_EXTRA_KEYS = (
    "guide.title", "guide.window", "guide.tour", "guide.intro", "guide.close",
    "guide.previous", "guide.next", "guide.preview", "guide.preview_window",
    "guide.open_tour", "guide.open_premium",
    "welcome.restart.title", "welcome.restart.note", "welcome.live.title", "welcome.live.note",
    "welcome.game_overlay.title", "welcome.game_overlay.note", "welcome.premium.title", "welcome.premium.note",
    "restart.enabled", "restart.fast_title", "restart.use", "restart.close_game",
    "live.demo", "live.snapshot", "live.bullet.stats", "live.bullet.recordings", "live.bullet.details",
    "overlay.demo", "topic.shady.secondary", "topic.roll.secondary",
)
_EXTRA = {
    "en": (
        "Quick Guides", "Quick Guides · BonkScanner", "Tour", "Choose a topic to get started.", "Close",
        "Previous", "Next", "Example", "BonkScanner · Guide preview", "Open tour", "Open Premium guide",
        "Find a map", "Templates, Scores and Auto-Reroll", "Review a run", "Live stats and recordings",
        "Game Overlay", "Widgets over your game", "Premium", "Explore features and activation",
        "On", "Quick restart in BonkScanner", "In {path}, select {button}.", "Close MegaBonk first if you need to change its settings file.",
        "Example recording", "Snapshot at {time}", "Live Loot: chest and key triggers, legendary actual vs expected.", "Scrub saved snapshots by time.", "Mob kills, damage sources, and Dice / Chaos counters when available in recordings.",
        "Overlay example", "Open history", "Open history",
    ),
    "ru": (
        "Короткие гиды", "Короткие гиды · BonkScanner", "Тур", "Выберите тему для начала.", "Закрыть",
        "Назад", "Далее", "Пример", "BonkScanner · Предпросмотр гида", "Открыть тур", "Открыть гид Premium",
        "Найти карту", "Templates, Scores и Auto-Reroll", "Изучить забег", "Статистика Live и записи",
        "Game Overlay", "Виджеты поверх игры", "Premium", "Все возможности и активация",
        "Вкл.", "Быстрый рестарт в BonkScanner", "В {path} нажмите {button}.", "Если нужно изменить файл настроек игры, сначала закройте MegaBonk.",
        "Пример записи", "Снимок на {time}", "Live Loot: срабатывания сундуков и ключей, фактические и ожидаемые легендарные предметы.", "Перемещайтесь по сохранённым снимкам во времени.", "Убийства монстров, источники урона и счётчики Dice / Chaos, если они доступны в записи.",
        "Пример оверлея", "Открыть историю", "Открыть историю",
    ),
    "uk": (
        "Короткі гіди", "Короткі гіди · BonkScanner", "Тур", "Оберіть тему, щоб почати.", "Закрити",
        "Назад", "Далі", "Приклад", "BonkScanner · Попередній перегляд гіда", "Відкрити тур", "Відкрити гід Premium",
        "Знайти мапу", "Templates, Scores і Auto-Reroll", "Переглянути забіг", "Статистика Live та записи",
        "Game Overlay", "Віджети поверх гри", "Premium", "Усі можливості й активація",
        "Увімк.", "Швидкий рестарт у BonkScanner", "У {path} натисніть {button}.", "Якщо потрібно змінити файл налаштувань гри, спочатку закрийте MegaBonk.",
        "Приклад запису", "Знімок на {time}", "Live Loot: спрацювання скринь і ключів, фактичні та очікувані легендарні предмети.", "Гортайте збережені знімки за часом.", "Убивства монстрів, джерела шкоди й лічильники Dice / Chaos, якщо вони доступні в записі.",
        "Приклад оверлею", "Відкрити історію", "Відкрити історію",
    ),
    "de": (
        "Kurzanleitungen", "Kurzanleitungen · BonkScanner", "Tour", "Wähle ein Thema für den Einstieg.", "Schließen",
        "Zurück", "Weiter", "Beispiel", "BonkScanner · Guide-Vorschau", "Tour öffnen", "Premium-Guide öffnen",
        "Karte finden", "Templates, Scores und Auto-Reroll", "Lauf ansehen", "Live-Werte und Aufnahmen",
        "Game Overlay", "Widgets über dem Spiel", "Premium", "Funktionen und Aktivierung ansehen",
        "An", "Schnellneustart in BonkScanner", "Wähle in {path} die Option {button}.", "Schließe MegaBonk zuerst, wenn du die Einstellungsdatei des Spiels ändern musst.",
        "Beispielaufnahme", "Schnappschuss bei {time}", "Live Loot: Auslösungen von Truhen und Schlüsseln sowie tatsächliche und erwartete legendäre Gegenstände.", "Navigiere zeitlich durch gespeicherte Schnappschüsse.", "Monster-Kills, Schadensquellen und Dice- / Chaos-Zähler, sofern in Aufnahmen verfügbar.",
        "Overlay-Beispiel", "Historie öffnen", "Historie öffnen",
    ),
    "fr": (
        "Guides rapides", "Guides rapides · BonkScanner", "Visite", "Choisissez un sujet pour commencer.", "Fermer",
        "Précédent", "Suivant", "Exemple", "BonkScanner · Aperçu du guide", "Ouvrir la visite", "Ouvrir le guide Premium",
        "Trouver une carte", "Templates, Scores et Auto-Reroll", "Revoir une partie", "Stats Live et enregistrements",
        "Game Overlay", "Widgets sur le jeu", "Premium", "Fonctions et activation",
        "Activé", "Redémarrage rapide dans BonkScanner", "Dans {path}, sélectionnez {button}.", "Fermez d'abord MegaBonk si vous devez modifier son fichier de paramètres.",
        "Exemple d'enregistrement", "Instantané à {time}", "Live Loot : déclenchements des coffres et clés, objets légendaires obtenus et attendus.", "Parcourez les instantanés sauvegardés dans le temps.", "Monstres éliminés, sources de dégâts et compteurs Dice / Chaos lorsqu'ils sont disponibles dans les enregistrements.",
        "Exemple d'overlay", "Ouvrir l'historique", "Ouvrir l'historique",
    ),
    "es": (
        "Guías rápidas", "Guías rápidas · BonkScanner", "Recorrido", "Elige un tema para empezar.", "Cerrar",
        "Anterior", "Siguiente", "Ejemplo", "BonkScanner · Vista previa de la guía", "Abrir recorrido", "Abrir guía Premium",
        "Buscar un mapa", "Templates, Scores y Auto-Reroll", "Revisar una partida", "Estadísticas Live y grabaciones",
        "Game Overlay", "Widgets sobre el juego", "Premium", "Funciones y activación",
        "Activado", "Reinicio rápido en BonkScanner", "En {path}, selecciona {button}.", "Cierra MegaBonk primero si necesitas modificar su archivo de ajustes.",
        "Grabación de ejemplo", "Captura en {time}", "Live Loot: activaciones de cofres y llaves, objetos legendarios reales frente a esperados.", "Recorre las capturas guardadas por tiempo.", "Enemigos eliminados, fuentes de daño y contadores Dice / Chaos cuando estén disponibles en grabaciones.",
        "Ejemplo de superposición", "Abrir historial", "Abrir historial",
    ),
    "pt": (
        "Guias rápidos", "Guias rápidos · BonkScanner", "Tour", "Escolha um tema para começar.", "Fechar",
        "Anterior", "Próximo", "Exemplo", "BonkScanner · Prévia do guia", "Abrir tour", "Abrir guia Premium",
        "Encontrar mapa", "Templates, Scores e Auto-Reroll", "Rever uma partida", "Estatísticas Live e gravações",
        "Game Overlay", "Widgets sobre o jogo", "Premium", "Recursos e ativação",
        "Ativado", "Reinício rápido no BonkScanner", "Em {path}, selecione {button}.", "Feche o MegaBonk primeiro se precisar alterar o arquivo de configurações do jogo.",
        "Exemplo de gravação", "Registro em {time}", "Live Loot: ativações de baús e chaves, itens lendários reais e esperados.", "Percorra os registros salvos por tempo.", "Monstros eliminados, fontes de dano e contadores Dice / Chaos quando disponíveis nas gravações.",
        "Exemplo de overlay", "Abrir histórico", "Abrir histórico",
    ),
}

MESSAGES: dict[str, dict[str, str]] = {
    language: {
        **{f"topic.{topic}.{field}": value
           for topic, values in topics.items()
           for field, value in zip(_TOPIC_FIELDS, values, strict=True)},
        **dict(zip(_EXTRA_KEYS, _EXTRA[language], strict=True)),
    }
    for language, topics in _TOPICS.items()
}

# Labels supplied by the application are inserted at render time.
_REFINEMENTS = {
    "en": (
        "Choose {templates} or {scores}, then press {start} to search.",
        "Loot: chest activity, key triggers, and actual vs expected legendary items.",
        "In recordings: scrub saved snapshots by time.",
        "Analysis: mob kills, damage sources, and Dice / Chaos counters when available in recordings.",
        "Open map-search guide", "What Premium includes", "Premium · {feature}", "Sample key",
        "Game example", "Markers on", "Markers off", "Show markers in example", "{count} confirmed rolls",
        "Offers across runs", "Offers", "Receive your BSK_… key", "Could not open the layout editor.",
    ),
    "ru": (
        "Выберите {templates} или {scores} и нажмите {start} для поиска.",
        "Loot: сундуки и срабатывания ключей, сколько легендарок выпало и сколько ожидалось.",
        "В записи: перемещайтесь по сохранённым снимкам во времени.",
        "Разбор: убийства монстров, источники урона и счётчики Dice / Chaos, если они доступны в записи.",
        "Открыть гид по поиску карты", "Что входит в Premium", "Premium · {feature}", "Пример ключа",
        "Пример игры", "Метки включены", "Метки скрыты", "Показывать метки в примере", "Подтверждённых выпадений: {count}",
        "Предложения за все забеги", "Предложений", "Получите ключ BSK_…", "Не удалось открыть редактор раскладки.",
    ),
    "uk": (
        "Оберіть {templates} або {scores} і натисніть {start} для пошуку.",
        "Loot: скрині й спрацювання ключів, фактичні та очікувані легендарні предмети.",
        "У записі: гортайте збережені знімки за часом.",
        "Аналіз: убивства монстрів, джерела шкоди й лічильники Dice / Chaos, якщо вони доступні в записі.",
        "Відкрити гід із пошуку мапи", "Що входить до Premium", "Premium · {feature}", "Приклад ключа",
        "Приклад гри", "Мітки ввімкнено", "Мітки приховано", "Показувати мітки в прикладі", "Підтверджених випадінь: {count}",
        "Пропозиції за всі забіги", "Пропозицій", "Отримайте ключ BSK_…", "Не вдалося відкрити редактор розкладки.",
    ),
    "de": (
        "Wähle {templates} oder {scores} und drücke {start} für die Suche.",
        "Loot: Truhen, Schlüsselauslösungen und tatsächliche gegenüber erwarteten legendären Gegenständen.",
        "In Aufnahmen: navigiere zeitlich durch gespeicherte Schnappschüsse.",
        "Analyse: Monster-Kills, Schadensquellen und Dice- / Chaos-Zähler, sofern in Aufnahmen verfügbar.",
        "Kartensuche-Guide öffnen", "Was Premium enthält", "Premium · {feature}", "Beispielschlüssel",
        "Spielbeispiel", "Markierungen an", "Markierungen aus", "Markierungen im Beispiel zeigen", "{count} bestätigte Würfe",
        "Angebote über alle Läufe", "Angebote", "Erhalte deinen BSK_…-Schlüssel", "Der Layouteditor konnte nicht geöffnet werden.",
    ),
    "fr": (
        "Choisissez {templates} ou {scores}, puis appuyez sur {start} pour lancer la recherche.",
        "Loot : coffres, déclenchements des clés et objets légendaires obtenus par rapport aux prévisions.",
        "Dans les enregistrements : parcourez les instantanés sauvegardés dans le temps.",
        "Analyse : monstres éliminés, sources de dégâts et compteurs Dice / Chaos lorsqu'ils sont disponibles dans les enregistrements.",
        "Ouvrir le guide de recherche de carte", "Ce que comprend Premium", "Premium · {feature}", "Exemple de clé",
        "Exemple de jeu", "Marqueurs affichés", "Marqueurs masqués", "Afficher les marqueurs dans l'exemple", "{count} tirages confirmés",
        "Offres de toutes les parties", "Offres", "Recevez votre clé BSK_…", "Impossible d'ouvrir l'éditeur de disposition.",
    ),
    "es": (
        "Elige {templates} o {scores} y pulsa {start} para buscar.",
        "Loot: cofres, activaciones de llaves y objetos legendarios reales frente a esperados.",
        "En grabaciones: recorre las capturas guardadas por tiempo.",
        "Análisis: enemigos eliminados, fuentes de daño y contadores Dice / Chaos cuando estén disponibles en grabaciones.",
        "Abrir guía de búsqueda de mapa", "Qué incluye Premium", "Premium · {feature}", "Clave de ejemplo",
        "Ejemplo de juego", "Marcadores activados", "Marcadores ocultos", "Mostrar marcadores en el ejemplo", "{count} tiradas confirmadas",
        "Ofertas entre partidas", "Ofertas", "Recibe tu clave BSK_…", "No se pudo abrir el editor de diseño.",
    ),
    "pt": (
        "Escolha {templates} ou {scores} e pressione {start} para buscar.",
        "Loot: baús, ativações de chaves e itens lendários reais em relação aos esperados.",
        "Na gravação: percorra os registros salvos por tempo.",
        "Análise: monstros eliminados, fontes de dano e contadores Dice / Chaos quando disponíveis nas gravações.",
        "Abrir guia de busca de mapa", "O que o Premium inclui", "Premium · {feature}", "Chave de exemplo",
        "Exemplo de jogo", "Marcadores ativados", "Marcadores ocultos", "Mostrar marcadores no exemplo", "{count} sorteios confirmados",
        "Ofertas entre partidas", "Ofertas", "Receba sua chave BSK_…", "Não foi possível abrir o editor de layout.",
    ),
}
_REFINEMENT_KEYS = (
    "topic.restart.summary", "live.bullet.stats", "live.bullet.recordings", "live.bullet.details",
    "guide.restart_hint", "guide.support_hint", "guide.premium_for", "guide.key_placeholder",
    "demo.game", "demo.markers_on", "demo.markers_off", "demo.show_markers", "demo.roll_total",
    "demo.shady_caption", "demo.offers", "demo.access_key", "demo.obs_error",
)
for _language, _values in _REFINEMENTS.items():
    MESSAGES[_language].update(zip(_REFINEMENT_KEYS, _values, strict=True))

_FINAL_COPY = {
    "en": ("Open {target}", "On the OBS tab, click {editor} to open the editor in your browser, then move and resize widgets.", "Show full-map markers, active powerups, and {luck} over the game.", "In recordings: scrub to see items and stats at a saved moment."),
    "ru": ("Открыть «{target}»", "На вкладке OBS нажмите «{editor}», чтобы открыть редактор в браузере, затем перемещайте виджеты и меняйте их размер.", "Большая карта с метками, активные усиления и виджет «{luck}» поверх игры.", "В записи: перемещайтесь по снимкам, чтобы увидеть предметы и статы в сохранённый момент."),
    "uk": ("Відкрити «{target}»", "На вкладці OBS натисніть «{editor}», щоб відкрити редактор у браузері, а потім переміщуйте віджети та змінюйте їхній розмір.", "Показуйте мітки повної мапи, активні підсилення та {luck} поверх гри.", "У записі: гортайте знімки, щоб побачити предмети й статистику в збережений момент."),
    "de": ("{target} öffnen", "Klicke im OBS-Tab auf {editor}, um den Editor im Browser zu öffnen. Verschiebe Widgets und ändere ihre Größe.", "Zeige Markierungen der vollständigen Karte, aktive Powerups und {luck} über dem Spiel.", "In Aufnahmen: navigiere zu einem gespeicherten Zeitpunkt, um Gegenstände und Werte zu sehen."),
    "fr": ("Ouvrir {target}", "Dans l'onglet OBS, cliquez sur {editor} pour ouvrir l'éditeur dans le navigateur, puis déplacez et redimensionnez les widgets.", "Affichez les marqueurs de la carte complète, les bonus actifs et {luck} sur le jeu.", "Dans les enregistrements : parcourez les instantanés pour voir les objets et stats au moment sauvegardé."),
    "es": ("Abrir {target}", "En la pestaña OBS, pulsa {editor} para abrir el editor en el navegador y mueve y redimensiona los widgets.", "Muestra los marcadores del mapa completo, las mejoras activas y {luck} sobre el juego.", "En grabaciones: recorre las capturas para ver objetos y estadísticas en el momento guardado."),
    "pt": ("Abrir {target}", "Na aba OBS, clique em {editor} para abrir o editor no navegador e mova e redimensione os widgets.", "Mostre marcadores do mapa completo, melhorias ativas e {luck} sobre o jogo.", "Na gravação: percorra os registros para ver itens e estatísticas no momento salvo."),
}
for _language, _values in _FINAL_COPY.items():
    MESSAGES[_language].update(zip(("guide.open_target", "topic.obs.summary", "topic.game_overlay.summary", "live.bullet.recordings"), _values, strict=True))
MESSAGES["ru"].update({
    "topic.restart.summary": "Выберите «{templates}» или «{scores}» и нажмите «{start}».",
    "restart.use": "Откройте {path} и нажмите «{button}».",
    "topic.restart.footnote": "Scanner держит клавишу дольше порога игры. Рекомендуемое удержание — 0,01 с порог + 0,05 с запас = 0,06 с.",
    "topic.game_overlay.footnote": "Настройте расположение виджетов во вкладке «Игровой оверлей».",
})

_OVERLAY_DETAIL_KEYS = (
    "overlay.kps.note", "overlay.stats.note", "overlay.luck_expected.note", "overlay.stage.note",
    "overlay.powerups.note", "overlay.map.note", "overlay.obs.workflow", "overlay.game.layout",
    "overlay.example_data", "overlay.luck_expected.title",
)
_OVERLAY_DETAILS = {
    "en": (
        "Current kill rate and averages for 60 seconds, 5 minutes, and the whole run.",
        "Live stats and caps. The Difficulty cap depends on the stage and time spent there.", "Observed item counts next to expected counts.",
        "Stage time, kills, and item counts.", "Active buffs and their remaining time.",
        "Marks tracked activity locations on the full map.",
        "Choose widgets in Scanner, add the Browser Source URL in OBS, and match the editor canvas size.",
        "Move widgets in layout mode and use each widget’s {scale} field to resize it.",
        "Widgets shown with example data", "{luck} with Expected",
    ),
    "ru": (
        "Текущая скорость убийств и средние значения за 60 секунд, 5 минут и весь забег.",
        "Статы и капы в реальном времени. Кап сложности зависит от этапа и времени на нём.", "Количество полученных предметов рядом с ожидаемым.",
        "Время этапа, убийства и количество предметов.", "Активные усиления и оставшееся время.",
        "Отмечает расположение отслеживаемых объектов на полной карте.",
        "Выберите виджеты в Scanner, добавьте URL источника браузера в OBS и укажите размер холста из редактора.",
        "Перетаскивайте виджеты в режиме редактирования. Размер каждого можно изменить в поле «{scale}».",
        "Виджеты с примером данных", "{luck} с ожидаемыми значениями",
    ),
    "uk": (
        "Поточна швидкість убивств і середні значення за 60 секунд, 5 хвилин і весь забіг.",
        "Характеристики й ліміти наживо. Ліміт складності залежить від етапу та часу на ньому.", "Кількість отриманих предметів поруч з очікуваною.",
        "Час етапу, вбивства та кількість предметів.", "Активні підсилення та час, що залишився.",
        "Позначає розташування відстежуваних об'єктів на повній мапі.",
        "Оберіть віджети в Scanner, додайте URL джерела браузера в OBS і вкажіть розмір полотна з редактора.",
        "У режимі редагування переміщуйте віджети, а їхній розмір змінюйте в полі «{scale}».",
        "Віджети з прикладом даних", "{luck} з очікуваними значеннями",
    ),
    "de": (
        "Aktuelle Killrate und Durchschnitt für 60 Sekunden, 5 Minuten und den gesamten Lauf.",
        "Live-Werte und Limits. Das Schwierigkeitslimit hängt von der Stage und ihrer Laufzeit ab.", "Erhaltene Gegenstände neben den erwarteten Anzahlen.",
        "Zeit, Kills und Gegenstände pro Stage.", "Aktive Verstärkungen und ihre Restdauer.",
        "Markiert Orte verfolgter Aktivitäten auf der vollständigen Karte.",
        "Wähle Widgets in Scanner, füge die Browserquellen-URL in OBS hinzu und übernimm die Leinwandgröße des Editors.",
        "Verschiebe Widgets im Layout-Modus und ändere ihre Größe im jeweiligen Feld „{scale}“.",
        "Widgets mit Beispieldaten", "{luck} mit Erwartungswerten",
    ),
    "fr": (
        "Éliminations par seconde et moyennes sur 60 secondes, 5 minutes et toute la partie.",
        "Stats et plafonds en direct. Le plafond de difficulté dépend de l’étape et du temps écoulé.", "Nombre d'objets obtenus à côté du nombre attendu.",
        "Temps, éliminations et objets par étape.", "Bonus actifs et temps restant.",
        "Marque les emplacements des activités suivies sur la carte complète.",
        "Choisissez les widgets dans Scanner, ajoutez l'URL de source navigateur dans OBS et reprenez la taille du canevas de l'éditeur.",
        "Déplacez les widgets en mode édition et réglez leur taille dans le champ « {scale} ».",
        "Widgets avec données d'exemple", "{luck} avec valeurs attendues",
    ),
    "es": (
        "Ritmo actual de bajas y medias de 60 segundos, 5 minutos y toda la partida.",
        "Estadísticas y límites en directo. El límite de dificultad depende de la etapa y del tiempo en ella.", "Cantidad de objetos obtenidos junto a la cantidad esperada.",
        "Tiempo, bajas y objetos por etapa.", "Mejoras activas y tiempo restante.",
        "Marca las ubicaciones de las actividades seguidas en el mapa completo.",
        "Elige los widgets en Scanner, añade la URL de fuente de navegador en OBS y usa el tamaño del lienzo del editor.",
        "Mueve los widgets en el modo de edición y ajusta su tamaño en el campo «{scale}».",
        "Widgets con datos de ejemplo", "{luck} con valores esperados",
    ),
    "pt": (
        "Taxa atual de eliminações e médias de 60 segundos, 5 minutos e toda a partida.",
        "Estatísticas e limites em tempo real. O limite de dificuldade depende da etapa e do tempo nela.", "Quantidade de itens obtidos ao lado da quantidade esperada.",
        "Tempo, eliminações e itens por etapa.", "Melhorias ativas e tempo restante.",
        "Marca a localização das atividades acompanhadas no mapa completo.",
        "Escolha os widgets no Scanner, adicione a URL da fonte de navegador no OBS e use o tamanho da tela do editor.",
        "Mova os widgets no modo de edição e ajuste o tamanho no campo «{scale}».",
        "Widgets com dados de exemplo", "{luck} com valores esperados",
    ),
}
for _language, _values in _OVERLAY_DETAILS.items():
    MESSAGES[_language].update(zip(_OVERLAY_DETAIL_KEYS, _values, strict=True))

_PREMIUM_DESCRIPTIONS = {
    "en": (
        "See marked activities on the minimap during a run.",
        "See Shady Guy’s last known stock and prices on the full map.",
        "Collect statistics on offers in the shops you visit.",
        "Collect roll history for Dice passive and Chaos Tome.",
    ),
    "ru": (
        "Метки объектов видны прямо на миникарте во время забега.",
        "Последний увиденный ассортимент и цены Shady Guy на большой карте.",
        "Сбор статистики по товарам из посещённых магазинов.",
        "Сбор истории выпадений от пассивки Dice и Тома Хаоса.",
    ),
    "uk": (
        "Позначки об’єктів видно прямо на мінімапі під час забігу.",
        "Останні відомі товари й ціни Shady Guy на великій мапі.",
        "Збирання статистики пропозицій відвіданих магазинів.",
        "Історія випадінь пасивної здібності Dice і Тома Хаосу.",
    ),
    "de": (
        "Sieh markierte Aktivitäten während des Laufs auf der Minimap.",
        "Sieh Shady Guys zuletzt bekanntes Angebot mit Preisen auf der großen Karte.",
        "Sammle Statistiken zu Angeboten in besuchten Läden.",
        "Sammle Würfe der passiven Fähigkeit von Dice und der Chaos-Schriftrolle.",
    ),
    "fr": (
        "Vois les activités marquées sur la minicarte pendant la partie.",
        "Retrouve le dernier stock connu et les prix de Shady Guy sur la carte.",
        "Collecte les statistiques des offres dans les boutiques visitées.",
        "Collecte l’historique des tirages du passif de Dice et du Tome du chaos.",
    ),
    "es": (
        "Consulta las actividades marcadas en el minimapa durante la partida.",
        "Consulta en el mapa el último inventario y los precios de Shady Guy.",
        "Recoge estadísticas de las ofertas de las tiendas que visitas.",
        "Recoge el historial de tiradas de la pasiva de Dice y del Tomo del Caos.",
    ),
    "pt": (
        "Veja as atividades marcadas no minimapa durante a partida.",
        "Veja no mapa o último estoque conhecido e os preços do Shady Guy.",
        "Colete estatísticas das ofertas das lojas que você visita.",
        "Colete o histórico de sorteios da habilidade passiva do Dice e do Tomo do Caos.",
    ),
}
for _language, _values in _PREMIUM_DESCRIPTIONS.items():
    _keys = ("minimap", "stock", "shady", "roll")
    MESSAGES[_language].update(
        (f"premium.feature.{key}", description) for key, description in zip(_keys, _values, strict=True)
    )

_RUN_SHORTCUTS = {
    "en": (
        "Drag A with LMB or click a stage card to jump there.",
        "Drag A with LMB or Shift + LMB. Drag B with Shift + RMB. Esc clears B.",
    ),
    "ru": (
        "Перетащите A левой кнопкой мыши или нажмите на карточку этапа, чтобы перейти к нему.",
        "Двигайте A через ЛКМ или Shift + ЛКМ, B через Shift + ПКМ. Esc убирает B.",
    ),
    "uk": (
        "Перетягніть A лівою кнопкою миші або натисніть картку етапу, щоб перейти до нього.",
        "Рухайте A лівою кнопкою (можна з Shift), а B — Shift + ПКМ. Esc прибирає B.",
    ),
    "de": (
        "Ziehe A mit der linken Maustaste oder klicke auf eine Abschnittskarte, um dorthin zu springen.",
        "Ziehe A mit der linken Maustaste, auch mit Shift. B ziehst du mit Shift und rechter Maustaste. Esc entfernt B.",
    ),
    "fr": (
        "Déplacez A par clic gauche ou cliquez sur une carte d’étape pour y accéder.",
        "Déplacez A par clic gauche, avec ou sans Maj, et B avec Maj + clic droit. Échap retire B.",
    ),
    "es": (
        "Arrastra A con el botón izquierdo o pulsa una tarjeta de etapa para ir a ella.",
        "Mueve A con clic izquierdo, con o sin Mayús, y B con Mayús + clic derecho. Esc quita B.",
    ),
    "pt": (
        "Arraste A com o botão esquerdo ou clique no cartão de uma fase para ir até ela.",
        "Mova A com clique esquerdo, com ou sem Shift, e B com Shift + clique direito. Esc remove B.",
    ),
}
for _language, _values in _RUN_SHORTCUTS.items():
    MESSAGES[_language].update(zip(("run.keys.timeline", "run.keys.compare"), _values, strict=True))

_RUN_SOURCE_COPY = {
    "en": ("{character} · {kills} kills", "{character} · recorded at {time}"),
    "ru": ("{character} · {kills} убийств", "{character} · снимок на {time}"),
    "uk": ("{character} · {kills} убивств", "{character} · знімок на {time}"),
    "de": ("{character} · {kills} Kills", "{character} · Aufnahme bei {time}"),
    "fr": ("{character} · {kills} éliminations", "{character} · capture à {time}"),
    "es": ("{character} · {kills} bajas", "{character} · captura a {time}"),
    "pt": ("{character} · {kills} eliminações", "{character} · captura em {time}"),
}
for _language, _values in _RUN_SOURCE_COPY.items():
    MESSAGES[_language].update(zip(("run.real_recording", "run.live_snapshot"), _values, strict=True))

for _language, _values in {
    "en": ("{count} stats", "Count", "Exp."),
    "ru": ("{count} характеристик", "Кол-во", "Ожид."),
    "uk": ("{count} характеристик", "К-сть", "Очік."),
    "de": ("{count} Werte", "Anz.", "Erw."),
    "fr": ("{count} caractéristiques", "Nbre", "Att."),
    "es": ("{count} estadísticas", "Cant.", "Esp."),
    "pt": ("{count} atributos", "Qtd.", "Esp."),
}.items():
    MESSAGES[_language].update(zip(
        ("roll.guide.stat_count", "roll.guide.count_short", "roll.guide.expected_short"), _values, strict=True,
    ))

_RUN_SCREEN_COPY = {
    "en": (
        "Point A shows the run during Time Stop at 51:11 in game. {powerups} and {diff_cap} are enabled.",
        "Compare two moments to see levels gained, kills, and items gained or lost between them.",
        "Switch between damage dealt and kills credited to each source.",
    ),
    "ru": (
        "Точка A показывает забег во время Time Stop на 51:11 по игровому таймеру. Включены «{powerups}» и «{diff_cap}».",
        "Сравните два момента, чтобы увидеть, сколько уровней и убийств прибавилось и какие предметы получили или потеряли.",
        "Переключайтесь между уроном и убийствами по каждому источнику.",
    ),
    "uk": (
        "Точка A показує забіг під час зупинки часу на 51:11 за ігровим таймером. Увімкнено «{powerups}» і «{diff_cap}».",
        "Порівняйте два моменти, щоб побачити приріст рівнів та вбивств, а також отримані й втрачені предмети.",
        "Перемикайтеся між шкодою та вбивствами за кожним джерелом.",
    ),
    "de": (
        "Punkt A zeigt den Lauf während des Zeitstopps bei 51:11 Spielzeit. „{powerups}“ und „{diff_cap}“ sind aktiviert.",
        "Vergleiche zwei Momente und sieh hinzugewonnene Stufen, Kills sowie erhaltene und verlorene Items.",
        "Wechsle zwischen verursachtem Schaden und Kills pro Quelle.",
    ),
    "fr": (
        "Le point A montre la partie pendant l’arrêt du temps, à 51:11 en jeu. « {powerups} » et « {diff_cap} » sont activés.",
        "Comparez deux moments pour voir les niveaux gagnés, les éliminations et les objets obtenus ou perdus.",
        "Basculez entre les dégâts infligés et les éliminations par source.",
    ),
    "es": (
        "El punto A muestra la partida durante la parada del tiempo, en 51:11 del juego. «{powerups}» y «{diff_cap}» están activados.",
        "Compara dos momentos para ver los niveles ganados, las bajas y los objetos obtenidos o perdidos.",
        "Alterna entre el daño infligido y las bajas atribuidas a cada fuente.",
    ),
    "pt": (
        "O ponto A mostra a partida durante a parada do tempo, em 51:11 no jogo. ‘{powerups}’ e ‘{diff_cap}’ estão ativados.",
        "Compare dois momentos para ver níveis ganhos, eliminações e itens ganhos ou perdidos.",
        "Alterne entre o dano causado e as eliminações atribuídas a cada fonte.",
    ),
}
for _language, _values in _RUN_SCREEN_COPY.items():
    MESSAGES[_language].update(zip(
        ("run.screen.timeline", "run.screen.compare", "run.screen.damage"),
        _values, strict=True,
    ))

_GUIDE_SHORTCUT_COPY = {
    "en": ("Guide", "Open the Premium guide.", "Premium is active. Open the Premium guide.", "Premium is active from a recent check. Open the Premium guide."),
    "ru": ("Гид", "Открыть гид Premium.", "Premium активен. Открыть гид Premium.", "Premium активен по результатам недавней проверки. Открыть гид Premium."),
    "uk": ("Гід", "Відкрити гід Premium.", "Premium активний. Відкрити гід Premium.", "Premium активний за результатами недавньої перевірки. Відкрити гід Premium."),
    "de": ("Guide", "Premium-Guide öffnen.", "Premium ist aktiv. Premium-Guide öffnen.", "Premium ist laut der letzten Prüfung aktiv. Premium-Guide öffnen."),
    "fr": ("Guide", "Ouvrir le guide Premium.", "Premium est actif. Ouvrir le guide Premium.", "Premium est actif d’après une vérification récente. Ouvrir le guide Premium."),
    "es": ("Guía", "Abrir la guía Premium.", "Premium está activo. Abrir la guía Premium.", "Premium está activo según una comprobación reciente. Abrir la guía Premium."),
    "pt": ("Guia", "Abrir o guia Premium.", "O Premium está ativo. Abrir o guia Premium.", "O Premium está ativo segundo uma verificação recente. Abrir o guia Premium."),
}
for _language, _values in _GUIDE_SHORTCUT_COPY.items():
    MESSAGES[_language].update(zip(
        ("guide.shortcut", "guide.premium_badge.inactive", "guide.premium_badge.online", "guide.premium_badge.cached"),
        _values, strict=True,
    ))


_LIVE_CARD_COPY = {
    "en": (
        "Track chests and key procs. Compare legendary drops with the expected count.",
        "See your Chaos Tome rolls and which stats they changed.",
        "See how much each stat gained from Charge Shrines.",
        "Inspect the character’s passive bonuses, including Dice rolls when available.",
    ),
    "ru": (
        "Следите за сундуками и срабатываниями ключей. Сравнивайте выпавшие легендарки с ожидаемым числом.",
        "Смотрите, какие статы изменились после бросков Тома Хаоса.",
        "Узнайте, сколько прибавили святилища к каждой характеристике.",
        "Проверяйте бонусы пассивки персонажа, например броски Dice.",
    ),
    "uk": (
        "Стежте за скринями й спрацюваннями ключів. Порівнюйте здобуті легендарні предмети з очікуваною кількістю.",
        "Дивіться, які характеристики змінилися після кидків Тома Хаосу.",
        "Дізнайтеся, скільки святилища додали до кожної характеристики.",
        "Перевіряйте бонуси пасивної здібності персонажа, наприклад кидки Dice.",
    ),
    "de": (
        "Verfolge Truhen und Schlüsselauslösungen. Vergleiche legendäre Funde mit der erwarteten Anzahl.",
        "Sieh, welche Werte sich durch Würfe der Chaos-Schriftrolle geändert haben.",
        "Sieh, wie viel die Charge Shrines zu jedem Wert beigetragen haben.",
        "Prüfe Boni der passiven Fähigkeit, etwa die Würfe von Dice.",
    ),
    "fr": (
        "Suivez les coffres et les activations de clés. Comparez les légendaires obtenus au nombre attendu.",
        "Voyez quelles stats les tirages du Tome du chaos ont modifiées.",
        "Voyez combien chaque stat a gagné grâce aux sanctuaires de charge.",
        "Consultez les bonus du passif du personnage, comme les tirages de Dice.",
    ),
    "es": (
        "Sigue los cofres y las activaciones de llaves. Compara los legendarios obtenidos con los esperados.",
        "Mira qué estadísticas cambiaron con las tiradas del Tomo del Caos.",
        "Consulta cuánto aportaron los santuarios de carga a cada estadística.",
        "Consulta los bonos de la pasiva del personaje, como las tiradas de Dice.",
    ),
    "pt": (
        "Acompanhe baús e ativações de chaves. Compare os lendários obtidos com o total esperado.",
        "Veja quais atributos mudaram com as rolagens do Tomo do Caos.",
        "Veja quanto os santuários de carga acrescentaram a cada atributo.",
        "Confira os bônus da passiva do personagem, como as rolagens de Dice.",
    ),
}
for _language, _values in _LIVE_CARD_COPY.items():
    MESSAGES[_language].update(zip(
        ("run.card.loot", "run.card.chaos", "run.card.shrines", "run.card.passives"), _values, strict=True,
    ))

_LIVE_METRIC_COPY = {
    "en": ("Expected {count}", "Chests opened", "Key procs: {count}"),
    "ru": ("Ожидалось {count}", "Открыто сундуков", "Срабатывания ключей: {count}"),
    "uk": ("Очікувалося {count}", "Відкрито скринь", "Спрацювання ключів: {count}"),
    "de": ("Erwartet: {count}", "Geöffnete Truhen", "Schlüsselauslösungen: {count}"),
    "fr": ("Attendu : {count}", "Coffres ouverts", "Activations de clés : {count}"),
    "es": ("Esperados: {count}", "Cofres abiertos", "Activaciones de llaves: {count}"),
    "pt": ("Esperados: {count}", "Baús abertos", "Ativações de chaves: {count}"),
}
for _language, _values in _LIVE_METRIC_COPY.items():
    MESSAGES[_language].update(zip(
        ("run.metric.expected", "run.metric.chests", "run.metric.keys"), _values, strict=True,
    ))
