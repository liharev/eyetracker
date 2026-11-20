"""Справка по настройкам (вкладка «Помощь», всплывающие подсказки и F1).

Каждый пункт: поле настроек (для значения по умолчанию и привязки к элементу окна),
подпись — точно как в окне настроек (переводится через tr), описание на русском и английском.
Значение по умолчанию берётся из Config() автоматически, поэтому не расходится с программой.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class HelpItem:
    label: str                       # подпись в окне настроек (ключ tr)
    ru: str
    en: str
    setting: Optional[str] = None    # "раздел.поле" в Config; None — кнопка/действие/индикатор
    widget: Optional[str] = None     # имя атрибута элемента в SettingsDialog (для подсказки)
    unit: str = ""                   # единица измерения (ключ tr), например " с"
    values: Dict[str, str] = field(default_factory=dict)   # значение → подпись (ключ tr)
    suffix_ru: str = ""              # уточнение заголовка, если подписи совпадают (например, «Таймаут»)
    suffix_en: str = ""


H = HelpItem

# (название вкладки — ключ tr, вступление ru, вступление en, пункты)
SECTIONS: List[Tuple[str, str, str, List[HelpItem]]] = [
    ("Общие",
     "Язык, значки, автозапуск и всё, что влияет на нагрузку на одноплатник.",
     "Language, icons, autostart and everything that affects the load on the single-board computer.",
     [
         H("Язык интерфейса:",
           "Язык окон, меню трея, событий журнала, писем и отчётов. «Как в системе» — русский, если язык "
           "системы русский, иначе английский. Окно настроек перестраивается сразу после «Применить». "
           "Уже записанные события журнала остаются на том языке, на котором были созданы.",
           "Language of the windows, tray menu, journal events, e-mails and reports. “System default” — "
           "Russian if the system language is Russian, otherwise English. The settings window is rebuilt right "
           "after “Apply”. Events already in the journal stay in the language they were created in.",
           "general.language", "language",
           values={"system": "Как в системе", "ru": "Русский", "en": "English"}),
         H("Цвет значков (меню, трей):",
           "Цвет буквы «C» в значке программы в меню приложений, в трее и в заголовках окон. «Автоматически» — "
           "белая на тёмной теме оформления и чёрная на светлой; тема отслеживается во время работы "
           "(в KDE учитывается стиль Plasma, т.е. цвет панели и меню). Выберите вручную, если автоматика "
           "ошиблась.",
           "Color of the “C” in the program icon in the application menu, tray and window title bars. "
           "“Automatic” — white on a dark theme and black on a light one; the theme is tracked while running "
           "(in KDE the Plasma style, i.e. the panel and menu color, is used). Choose manually if the automatic "
           "choice is wrong.",
           "general.tray_icon_color", "tray_color",
           values={"auto": "Автоматически (по теме оформления)", "light": "Белые (для тёмной темы)",
                   "dark": "Чёрные (для светлой темы)"}),
         H("Запускать автоматически при входе в систему",
           "Программа запускается в фоне при входе пользователя в графический сеанс. Выключать не рекомендуется: "
           "без запуска контроль не работает.",
           "The program starts in the background when the user logs into the graphical session. Turning it off "
           "is not recommended: monitoring does not work unless the program is running.",
           "general.autostart", "autostart"),
         H("Нейросети выполнять на:",
           "Где выполнять поиск, распознавание лиц и оценку взгляда. NPU (нейропроцессор RK3588) почти не "
           "нагружает процессор: на ROCK 5T нагрузка программы снижается примерно вдвое. «Автоматически» — "
           "NPU, если он доступен, иначе процессор. Если NPU выбран, но не запустился, программа сама работает "
           "на CPU (причина — на вкладке «Диагностика»).",
           "Where face detection, recognition and gaze estimation run. The NPU (RK3588 neural processor) "
           "barely loads the CPU: on the ROCK 5T the program load drops by about half. “Automatic” — the NPU "
           "if available, otherwise the CPU. If the NPU is selected but fails to start, the program "
           "automatically uses the CPU (the reason is shown on the “Diagnostics” tab).",
           "processing.accelerator", "accel",
           values={"auto": "Автоматически (NPU, если доступен)", "npu": "NPU RK3588",
                   "cpu": "Только процессор (CPU)"}),
         H("Ядро NPU:",
           "У NPU RK3588 три ядра. «Автоматически» — выбирает драйвер. Укажите конкретное ядро, если другие "
           "программы тоже используют NPU и нужно разнести нагрузку. Задачи программы на NPU всегда идут с "
           "низким приоритетом.",
           "The RK3588 NPU has three cores. “Automatic” — chosen by the driver. Specify a core if other "
           "programs also use the NPU and the load should be separated. The program's NPU tasks always run "
           "with low priority.",
           "processing.npu_core", "npu_core",
           values={"auto": "Автоматически", "0": "Ядро 0", "1": "Ядро 1", "2": "Ядро 2"}),
         H("Частота анализа (есть люди):",
           "Сколько кадров в секунду анализируется, когда перед экраном кто-то есть. Больше — быстрее реакция, "
           "но выше нагрузка. Для таймаутов, измеряемых секундами, достаточно 3–5.",
           "How many frames per second are analyzed when someone is in front of the screen. Higher means "
           "faster reaction but more load. 3–5 is enough for timeouts measured in seconds.",
           "processing.fps", "fps", unit=" кадр/с"),
         H("Частота анализа (никого нет):",
           "Частота анализа, когда перед экраном никого нет: программа лишь ждёт появления человека, поэтому "
           "частота снижена ради экономии ресурсов. Влияет на то, как быстро будет замечен подошедший.",
           "Analysis rate when nobody is in front of the screen: the program only waits for someone to appear, "
           "so the rate is lowered to save resources. Affects how quickly an approaching person is noticed.",
           "processing.idle_fps", "idle_fps", unit=" кадр/с"),
         H("Ширина кадра для детектора (CPU):",
           "До какого размера уменьшается кадр перед поиском лиц на процессоре. Меньше — быстрее, но хуже "
           "находятся мелкие (далёкие) лица. На NPU не используется (там фиксированный размер 320×256).",
           "The size the frame is reduced to before face detection on the CPU. Smaller is faster but small "
           "(distant) faces are found worse. Not used on the NPU (fixed 320×256 there).",
           "processing.detect_width", "detect_width", unit=" px"),
         H("Ядра CPU:",
           "На каких ядрах процессора разрешено работать программе. «auto» — только энергоэффективные ядра "
           "(на RK3588 — Cortex-A55, cpu0–3), чтобы производительные ядра A76 оставались другим программам. "
           "Можно указать список, например «0-3» или «0,1». Пусто — без ограничения. Применяется после "
           "перезапуска программы.",
           "Which CPU cores the program may run on. “auto” — efficiency cores only (on RK3588 — Cortex-A55, "
           "cpu0–3), so that the performance A76 cores remain for other programs. You can enter a list, e.g. "
           "“0-3” or “0,1”. Empty — no restriction. Takes effect after restarting the program.",
           "processing.cpu_cores", "cpu_cores"),
         H("Приоритет (nice):",
           "Приоритет процесса программы: 0 — обычный, 19 — самый низкий. Чем выше число, тем охотнее система "
           "отдаёт процессор другим программам. Применяется после перезапуска программы.",
           "Process priority of the program: 0 — normal, 19 — lowest. The higher the number, the more readily "
           "the system gives the CPU to other programs. Takes effect after restarting the program.",
           "processing.nice", "nice"),
         H("Полный просмотр кадра каждые:",
           "Как часто проверяется весь кадр. Между полными просмотрами лица ищутся только рядом с уже найденными "
           "— это в несколько раз дешевле. Новое лицо (например, постороннее) будет замечено не позже, чем через "
           "этот интервал. Если лицо потерялось, весь кадр проверяется сразу.",
           "How often the whole frame is checked. Between full scans, faces are searched only near already found "
           "faces — several times cheaper. A new (e.g. unknown) face is noticed within this interval. If a face "
           "is lost, the whole frame is checked immediately.",
           "processing.full_scan_interval_s", "full_scan", unit=" с"),
         H("Оценка взгляда (без предупреждения):",
           "Сколько раз в секунду оценивается взгляд, пока рамки нет. Пока предупреждения нет, частая оценка не "
           "нужна; как только появилась рамка, взгляд оценивается на каждом кадре, чтобы рамка и звук исчезали "
           "сразу при возвращении взгляда.",
           "How many times per second the gaze is estimated while there is no frame. Frequent estimation is not "
           "needed while there is no warning; once the frame appears, the gaze is estimated on every frame so "
           "that the frame and sound disappear as soon as the gaze returns.",
           "processing.gaze_fps", "gaze_fps", unit=" раз/с"),
         H("Точная оценка взгляда по радужке (модель точек лица)",
           "Включено — взгляд оценивается по повороту головы и положению радужек глаз (точнее). Выключено — "
           "только по повороту головы (меньше нагрузка, но взгляд, отведённый одними глазами, не заметен). "
           "После переключения выполните калибровку заново.",
           "On — the gaze is estimated from head rotation and the position of the irises (more precise). Off — "
           "from head rotation only (less load, but looking away with the eyes alone is not noticed). "
           "Recalibrate after switching.",
           "processing.precise_gaze", "use_mp"),
         H("Хранить события:",
           "Сколько дней хранить события и снимки в журнале; более старые удаляются автоматически (кроме ещё не "
           "отправленных в отчёте). 0 — хранить бессрочно.",
           "How many days to keep events and snapshots in the journal; older ones are deleted automatically "
           "(except those not yet sent in a report). 0 — keep forever.",
           "general.log_retention_days", "retention", unit=" дн."),
     ]),
    ("Камера",
     "Источник изображения. Изменения вступают в силу по кнопке «Применить»; справа видно изображение с "
     "найденными лицами.",
     "The image source. Changes take effect after “Apply”; the image with detected faces is shown on the right.",
     [
         H("Источник:",
           "Камера: номер («0»), устройство («/dev/video0») или конвейер GStreamer для MIPI-камеры. Номер "
           "устройства USB-камеры можно узнать командой «v4l2-ctl --list-devices» — нужен первый пункт в её блоке.",
           "Camera: a number (“0”), a device (“/dev/video0”) or a GStreamer pipeline for a MIPI camera. "
           "The USB camera device can be found with “v4l2-ctl --list-devices” — use the first entry in its block.",
           "camera.source", "cam_source"),
         H("Драйвер:",
           "Способ доступа к камере. «Автоматически» подходит для USB-камер (используется V4L2). GStreamer нужен "
           "для конвейеров GStreamer (требует сборку OpenCV с GStreamer).",
           "How the camera is accessed. “Automatic” suits USB cameras (V4L2 is used). GStreamer is needed for "
           "GStreamer pipelines (requires an OpenCV build with GStreamer).",
           "camera.backend", "cam_backend",
           values={"auto": "Автоматически", "v4l2": "V4L2", "gstreamer": "GStreamer", "ffmpeg": "FFmpeg"}),
         H("Ширина:", "Запрашиваемая ширина кадра. 640 — оптимум по нагрузке и точности; больше — лишняя нагрузка.",
           "Requested frame width. 640 is the optimum for load and accuracy; more is unnecessary load.",
           "camera.width", "cam_w", unit=" px"),
         H("Высота:", "Запрашиваемая высота кадра (обычно 480).", "Requested frame height (usually 480).",
           "camera.height", "cam_h", unit=" px"),
         H("Частота захвата:",
           "Сколько кадров в секунду камера отдаёт. Анализируются не все кадры (см. «Частота анализа»), но "
           "меньшая частота камеры снижает нагрузку на USB и драйвер.",
           "How many frames per second the camera delivers. Not every frame is analyzed (see “Analysis rate”), "
           "but a lower camera rate reduces the USB and driver load.",
           "camera.fps", "cam_fps", unit=" кадр/с"),
         H("Поворот:", "Поворот изображения, если камера закреплена боком или вверх ногами.",
           "Image rotation if the camera is mounted sideways or upside down.", "camera.rotate", "cam_rotate",
           unit="°"),
         H("Зеркально", "Зеркальное отражение изображения. На распознавание не влияет; после изменения выполните "
           "калибровку взгляда заново.",
           "Mirrors the image. Does not affect recognition; recalibrate the gaze after changing it.",
           "camera.mirror", "cam_mirror"),
     ]),
    ("База лиц",
     "Авторизованные пользователи. Пока база пуста, правила 4, 5 и 6 не действуют (защита от блокировки самого "
     "себя).",
     "Authorized users. While the database is empty, rules 4, 5 and 6 are inactive (protection against locking "
     "yourself out).",
     [
         H("Добавить лицо…",
           "Новый авторизованный пользователь: 10 снимков с камеры (во время съёмки медленно поворачивайте "
           "голову) или фотографии. В кадре должен быть один человек.",
           "A new authorized user: 10 camera captures (slowly turn your head while capturing) or photos. Only "
           "one person must be in view."),
         H("Добавить образцы…",
           "Дополнительные снимки для выбранного человека — например, в очках, при другом освещении или после "
           "смены причёски. Повышает надёжность распознавания.",
           "Additional captures for the selected person — e.g. with glasses, in different lighting or after a "
           "new haircut. Improves recognition reliability."),
         H("Переименовать…", "Изменить имя выбранного человека (используется в журнале и письмах).",
           "Change the selected person's name (used in the journal and e-mails)."),
         H("Удалить", "Удалить человека и все его образцы из базы.",
           "Delete the person and all their samples from the database."),
         H("Порог сходства лица:",
           "Насколько лицо должно быть похоже на образцы, чтобы считаться авторизованным. Выше — строже: меньше "
           "ошибочных «своих», но чаще «посторонний» для настоящего пользователя. Рекомендуется 0.36–0.45; если "
           "вас иногда принимают за постороннего — уменьшите, если посторонних принимают за вас — увеличьте.",
           "How similar a face must be to the samples to count as authorized. Higher is stricter: fewer false "
           "matches but more often “unknown” for the real user. 0.36–0.45 is recommended; if you are sometimes "
           "taken for a stranger — lower it, if strangers are taken for you — raise it.",
           "processing.recognition_threshold", "rec_thr"),
         H("Порог детектора лиц:",
           "Уверенность, с которой изображение считается лицом. Ниже — находятся лица в профиль и при плохом "
           "освещении, но возможны ложные «лица»; выше — наоборот.",
           "Confidence at which something is considered a face. Lower finds faces in profile and in poor "
           "lighting but may give false “faces”; higher — the opposite.",
           "processing.detect_threshold", "det_thr"),
         H("Мин. размер лица для распознавания:",
           "Лица меньше этого размера (далеко от камеры) не распознаются, а учитываются только как присутствие "
           "человека — это защищает от ошибочного «постороннего» на заднем плане.",
           "Faces smaller than this (far from the camera) are not recognized and only count as a person's "
           "presence — this prevents false “unknown face” alarms from the background.",
           "processing.min_face_size", "min_face", unit=" px"),
         H("Перепроверка известных лиц каждые:",
           "Как часто повторно распознаётся уже опознанный человек (на случай подмены). Новые лица распознаются "
           "сразу. Реже — меньше нагрузка.",
           "How often an already identified person is recognized again (in case of substitution). New faces are "
           "recognized immediately. Less often means less load.",
           "processing.recognize_interval_s", "rec_interval", unit=" с"),
     ]),
    ("Блокировка",
     "Пункты 1, 3, 4 и 5: когда считать, что человек ушёл, и когда блокировать экран.",
     "Items 1, 3, 4 and 5: when a person is considered gone and when to lock the screen.",
     [
         H("Человек считается ушедшим через:",
           "Сколько секунд лицо должно отсутствовать, чтобы записать событие «перед экраном никого нет». "
           "Защищает от ложных событий при кратковременной потере лица (наклонился, отвернулся).",
           "How many seconds the face must be absent to record the “nobody in front of the screen” event. "
           "Prevents false events when the face is briefly lost (leaned, turned away).",
           "presence.leave_debounce_s", "leave_debounce", unit=" с"),
         H("3. Блокировка, если перед экраном никого нет",
           "Включено — экран блокируется, если перед камерой никого нет дольше таймаута.",
           "On — the screen is locked if nobody is in front of the camera longer than the timeout.",
           "presence.lock_on_absence", "lock_abs"),
         H("Таймаут:",
           "Для пункта 3: сколько секунд перед экраном никого не должно быть до блокировки.",
           "For item 3: how many seconds nobody must be in front of the screen before locking.",
           "presence.absence_timeout_s", "abs_timeout", unit=" с", suffix_ru=" (п. 3)", suffix_en=" (item 3)"),
         H("4. Блокировка, если нет авторизованного лица (даже при наличии других)",
           "Включено — экран блокируется, если среди лиц в кадре нет ни одного из базы (или лиц нет вообще) "
           "дольше таймаута этого пункта.",
           "On — the screen is locked if none of the faces in view is from the database (or there are no faces "
           "at all) longer than this item's timeout.",
           "authorized.lock_if_no_authorized", "lock_unauth"),
         H("Таймаут:",
           "Для пункта 4: сколько секунд в кадре не должно быть авторизованного лица до блокировки.",
           "For item 4: how many seconds there must be no authorized face in view before locking.",
           "authorized.timeout_s", "unauth_timeout", unit=" с", suffix_ru=" (п. 4)", suffix_en=" (item 4)"),
         H("5. Блокировка при появлении постороннего лица (даже рядом с авторизованным)",
           "Включено — экран блокируется, если в кадре появилось лицо не из базы, даже если рядом авторизованный "
           "пользователь (например, кто-то смотрит из-за плеча).",
           "On — the screen is locked when a face not from the database appears, even next to an authorized "
           "user (e.g. someone looking over the shoulder).",
           "stranger.lock_on_stranger", "lock_stranger"),
         H("Время подтверждения:",
           "Сколько секунд постороннее лицо должно быть видно до блокировки — защищает от ложных срабатываний "
           "(блики, кратковременные ошибки распознавания).",
           "How many seconds an unknown face must be visible before locking — prevents false alarms (glare, "
           "brief recognition errors).",
           "stranger.confirm_s", "stranger_confirm", unit=" с"),
         H("Метод:",
           "Как блокировать экран. «Автоматически» — подбирается команда для вашего рабочего стола (KDE, GNOME, "
           "Xfce и др.). «Своя команда» — если автоматика не сработала.",
           "How to lock the screen. “Automatic” — a command suitable for your desktop (KDE, GNOME, Xfce, etc.) "
           "is chosen. “Custom command” — if the automatic one does not work.",
           "lock.method", "lock_method",
           values={"auto": "Автоматически (loginctl / D-Bus / xflock4 / …)", "custom": "Своя команда"}),
         H("Команда:",
           "Своя команда блокировки, например «loginctl lock-session» (KDE) или «xflock4» (Xfce). Используется, "
           "если выбран метод «Своя команда».",
           "Custom lock command, e.g. “loginctl lock-session” (KDE) or “xflock4” (Xfce). Used when the “Custom "
           "command” method is selected.",
           "lock.custom_command", "lock_cmd"),
         H("Повторная блокировка через:",
           "Если после разблокировки условие блокировки всё ещё выполняется (например, посторонний остался), "
           "экран блокируется снова через это время. Работает, если рабочий стол сообщает состояние блокировки.",
           "If the lock condition still holds after unlocking (e.g. the stranger is still there), the screen is "
           "locked again after this time. Works if the desktop reports the lock state.",
           "lock.relock_interval_s", "relock", unit=" с"),
         H("Проверить блокировку сейчас", "Немедленно заблокировать экран выбранным способом — для проверки.",
           "Lock the screen immediately using the selected method — for testing."),
     ]),
    ("Взгляд",
     "Пункт 6: контроль того, что авторизованный пользователь смотрит на экран. Все времена отсчитываются с "
     "момента, когда взгляд ушёл с экрана; при возвращении взгляда всё сбрасывается.",
     "Item 6: checking that the authorized user is looking at the screen. All times are counted from the moment "
     "the gaze leaves the screen; everything is reset when the gaze returns.",
     [
         H("Включено", "Включает контроль взгляда авторизованного пользователя.",
           "Enables gaze control of the authorized user.", "gaze.enabled", "gaze_on"),
         H("Красная рамка через:",
           "Через сколько секунд после ухода взгляда по краям экрана появляется красная рамка.",
           "How many seconds after the gaze leaves the screen a red frame appears around the screen edges.",
           "gaze.t1_s", "t1", unit=" с"),
         H("Мигающая рамка через:",
           "Через сколько секунд рамка начинает мигать. Не может быть меньше времени красной рамки.",
           "After how many seconds the frame starts blinking. Cannot be less than the red frame time.",
           "gaze.t2_s", "t2", unit=" с"),
         H("Звуковой сигнал через:",
           "Через сколько секунд включается звуковой сигнал (рамка продолжает мигать). Не может быть меньше "
           "времени мигающей рамки.",
           "After how many seconds the sound alert starts (the frame keeps blinking). Cannot be less than the "
           "blinking frame time.",
           "gaze.t3_s", "t3", unit=" с"),
         H("Уведомление на e-mail через:",
           "Через сколько секунд отправляется письмо о том, что взгляд не на экране (одно письмо за эпизод). "
           "Доступно, только если на вкладке «Уведомления» для события «6. Контроль взгляда» отмечено «E-mail "
           "сразу» и настроен почтовый сервер.",
           "After how many seconds an e-mail about the gaze being off the screen is sent (one e-mail per "
           "episode). Available only if “E-mail immediately” is checked for the “6. Gaze control” event on the "
           "“Notifications” tab and the mail server is configured.",
           "gaze.t4_s", "t4", unit=" с"),
         H("Взгляд считается вернувшимся через:",
           "Сколько секунд взгляд должен быть на экране, чтобы предупреждения сбросились. Защищает от сброса "
           "из-за мимолётного взгляда.",
           "How many seconds the gaze must stay on the screen for the warnings to be reset. Prevents resets "
           "caused by a fleeting glance.",
           "gaze.return_debounce_s", "ret_debounce", unit=" с"),
         H("Пропажа лица из кадра (отвернулся) = взгляд не на экране",
           "Включено — если авторизованный пользователь отвернулся так, что лицо пропало из кадра, это считается "
           "отводом взгляда. Выключено — контроль приостанавливается, пока лицо не вернётся.",
           "On — if the authorized user turns away so that the face disappears from view, it counts as looking "
           "away. Off — the control pauses until the face returns.",
           "gaze.face_lost_is_away", "lost_away"),
         H("Закрытые глаза = взгляд не на экране",
           "Включено — долго закрытые глаза считаются отводом взгляда (например, задремал). Обычное моргание "
           "не влияет.",
           "On — eyes closed for a long time count as looking away (e.g. dozing off). Normal blinking has no "
           "effect.",
           "gaze.eyes_closed_is_away", "closed_away"),
         H("По горизонтали от:",
           "Левая граница зоны «взгляд на экране» в градусах (влево — отрицательные). Обычно задаётся "
           "калибровкой, а не вручную.",
           "Left boundary of the “gaze on screen” zone in degrees (left is negative). Usually set by "
           "calibration rather than manually.",
           "gaze.zone_yaw_min", "yaw_min", unit="°"),
         H("По горизонтали до:", "Правая граница зоны «взгляд на экране» в градусах.",
           "Right boundary of the “gaze on screen” zone in degrees.", "gaze.zone_yaw_max", "yaw_max", unit="°"),
         H("По вертикали от (вниз):",
           "Нижняя граница зоны в градусах. Камера над экраном, поэтому взгляд на экран — это отрицательные углы.",
           "Lower boundary of the zone in degrees. The camera is above the screen, so looking at the screen means "
           "negative angles.", "gaze.zone_pitch_min", "pitch_min", unit="°"),
         H("По вертикали до (вверх):", "Верхняя граница зоны в градусах.", "Upper boundary of the zone in degrees.",
           "gaze.zone_pitch_max", "pitch_max", unit="°"),
         H("Допуск:",
           "Запас в градусах вокруг зоны экрана. Больше — меньше ложных предупреждений, но взгляд чуть мимо "
           "экрана не будет замечен.",
           "Margin in degrees around the screen zone. More means fewer false warnings, but looking slightly past "
           "the screen will not be noticed.", "gaze.zone_margin", "zone_margin", unit="°"),
         H("Коэффициент поворота глаз:",
           "Насколько смещение радужки переводится в поворот взгляда. Менять обычно не нужно — калибровка "
           "учитывает особенности пользователя.",
           "How strongly the iris displacement translates into gaze rotation. Usually there is no need to change "
           "it — calibration accounts for the user's specifics.", "gaze.eye_gain", "eye_gain"),
         H("Калибровать…",
           "Настройка зоны экрана под пользователя и монитор: сядьте как обычно и посмотрите на 5 точек на "
           "экране. Выполните после установки, смены монитора, положения камеры или рабочего места; затем "
           "нажмите «Применить».",
           "Adjusts the screen zone to the user and monitor: sit as usual and look at 5 dots on the screen. Do it "
           "after installation and after changing the monitor, camera position or workplace; then press "
           "“Apply”."),
         H("Сейчас:",
           "Текущие углы взгляда и попадает ли он в зону экрана — удобно для проверки калибровки.",
           "Current gaze angles and whether they fall into the screen zone — handy for checking the calibration."),
         H("Толщина:", "Толщина красной рамки по краям экрана.", "Thickness of the red frame around the screen edges.",
           "gaze.border_width", "border_w", unit=" px"),
         H("Цвет:", "Цвет рамки.", "Frame color.", "gaze.border_color", "border_color"),
         H("Период мигания:", "Скорость мигания рамки: время одного включения или выключения.",
           "Frame blinking speed: duration of one on or off phase.", "gaze.blink_interval_ms", "blink_ms",
           unit=" мс"),
         H("Сигнал:",
           "Звук, который проигрывается, когда взгляд долго не на экране: три встроенных или свой файл "
           "(кнопка «Загрузить…»; WAV, OGG, FLAC, MP3). ▶ — прослушать.",
           "The sound played when the gaze has been off the screen for a long time: three built-in ones or your "
           "own file (the “Upload…” button; WAV, OGG, FLAC, MP3). ▶ — listen.",
           "gaze.sound", "sound",
           values={"builtin:beep": "Короткий сигнал (3 гудка)", "builtin:chime": "Двухтональный звонок",
                   "builtin:siren": "Сирена"}),
         H("Пауза между повторами:", "Пауза между повторениями сигнала, пока взгляд не вернётся.",
           "Pause between sound repetitions until the gaze returns.", "gaze.sound_repeat_s", "sound_repeat",
           unit=" с"),
         H("Громкость:", "Громкость сигнала, %.", "Sound volume, %.", "gaze.volume", "volume"),
     ]),
    ("Уведомления",
     "Куда направлять события по пунктам 1–6 и служебные, и как отправлять письма.",
     "Where to send events for items 1–6 and service events, and how to send e-mails.",
     [
         H("E-mail сразу",
           "Письмо отправляется в момент события. Для контроля взгляда — одно письмо, когда взгляд не на экране "
           "дольше времени «Уведомление на e-mail через».",
           "An e-mail is sent at the moment of the event. For gaze control — one e-mail when the gaze stays off "
           "the screen longer than the “E-mail notification after” time."),
         H("В журнал", "Событие записывается в журнал (вкладка «Журнал»).",
           "The event is recorded in the journal (the “Journal” tab)."),
         H("Журнал + e-mail по расписанию",
           "Событие записывается в журнал и попадает в отчёт, который отправляется по расписанию (раздел «Отчёт "
           "по расписанию»).",
           "The event is recorded in the journal and included in the report sent on schedule (the “Scheduled "
           "report” section)."),
         H("Сохранять снимок с камеры для событий в журнале",
           "К событиям в журнале сохраняется кадр с камеры (открывается двойным щелчком). Занимает место на "
           "диске; старые снимки удаляются вместе с событиями.",
           "A camera frame is saved with journal events (opened with a double-click). Takes disk space; old "
           "snapshots are deleted along with the events.", "notify.save_snapshots", "save_snaps"),
         H("Сервер:", "Адрес почтового сервера (SMTP) для отправки писем, например smtp.yandex.ru.",
           "Mail (SMTP) server address for sending e-mails, e.g. smtp.gmail.com.", "email.smtp_host", "smtp_host"),
         H("Порт:", "Порт SMTP: обычно 465 для SSL/TLS и 587 для STARTTLS.",
           "SMTP port: usually 465 for SSL/TLS and 587 for STARTTLS.", "email.smtp_port", "smtp_port"),
         H("Шифрование:", "Способ защиты соединения с почтовым сервером — как указано в настройках вашей почты.",
           "How the connection to the mail server is protected — as specified by your mail provider.",
           "email.security", "smtp_sec",
           values={"starttls": "STARTTLS", "ssl": "SSL/TLS", "none": "Без шифрования"}),
         H("Логин:", "Имя пользователя почтового ящика — обычно полный адрес.",
           "Mailbox user name — usually the full address.", "email.username", "smtp_user"),
         H("Пароль:",
           "Пароль почтового ящика. Для Яндекса, Mail.ru и Gmail нужен «пароль приложения», созданный в "
           "настройках безопасности ящика. Хранится в файле настроек с доступом только для вас.",
           "Mailbox password. Yandex, Mail.ru and Gmail require an “app password” created in the mailbox "
           "security settings. Stored in the settings file readable only by you.", "email.password", "smtp_pass"),
         H("Отправитель:", "Адрес отправителя писем; пусто — используется логин.",
           "Sender address; empty — the login is used.", "email.sender", "smtp_from"),
         H("Получатель(и):", "Кому отправлять письма: один или несколько адресов через запятую.",
           "Who receives the e-mails: one or several comma-separated addresses.", "email.recipients", "smtp_to"),
         H("Префикс темы:", "Текст в начале темы каждого письма — удобно для фильтров почты.",
           "Text at the start of every e-mail subject — handy for mail filters.", "email.subject_prefix",
           "smtp_prefix"),
         H("Прикладывать снимок с камеры к письму", "К письму о событии прикладывается кадр с камеры.",
           "A camera frame is attached to the event e-mail.", "email.attach_snapshot", "attach_snap"),
         H("Отправить тестовое письмо", "Проверка настроек почты: отправляется пробное письмо получателям.",
           "Checks the mail settings: a test e-mail is sent to the recipients."),
         H("Расписание:",
           "Когда отправлять отчёт о событиях, отмеченных «Журнал + e-mail по расписанию»: каждые N минут или "
           "ежедневно в заданное время. Отчёт содержит сводку и все события во вложении CSV.",
           "When to send the report on events marked “Journal + scheduled e-mail”: every N minutes or daily at "
           "set times. The report contains a summary and all events in a CSV attachment.",
           "schedule.mode", "sched_mode",
           values={"interval": "Каждые N минут", "daily": "Ежедневно в указанное время"}),
         H("Интервал:", "Для режима «Каждые N минут» — период отправки отчёта.",
           "For the “Every N minutes” mode — the report period.", "schedule.interval_min", "sched_interval",
           unit=" мин"),
         H("Время (ЧЧ:ММ через запятую):",
           "Для режима «Ежедневно» — время отправки, например «09:00, 18:00».",
           "For the “Daily” mode — sending times, e.g. “09:00, 18:00”.", "schedule.daily_times", "sched_times"),
         H("Отправлять отчёт, даже если новых событий нет",
           "Включено — отчёт приходит всегда (подтверждает, что программа работает); выключено — только при "
           "наличии новых событий.",
           "On — the report always arrives (confirms the program is running); off — only when there are new "
           "events.", "schedule.send_empty", "sched_empty"),
         H("Отправить отчёт сейчас", "Немедленно отправить отчёт о накопленных событиях.",
           "Send the report on accumulated events immediately."),
     ]),
    ("Журнал",
     "События, записанные согласно вкладке «Уведомления».",
     "Events recorded according to the “Notifications” tab.",
     [
         H("Все события", "Фильтр журнала по категории события.", "Filters the journal by event category."),
         H("Экспорт CSV…", "Сохранение событий (с учётом фильтра) в файл CSV для Excel/LibreOffice.",
           "Saves the events (with the filter applied) to a CSV file for Excel/LibreOffice."),
         H("Очистить…", "Удаление всех событий и снимков из журнала (записывается служебное событие).",
           "Deletes all events and snapshots from the journal (a service event is recorded)."),
     ]),
    ("Диагностика",
     "Ресурсы одноплатника, которые использует программа, в реальном времени. Цвет шкал: зелёный — норма, "
     "жёлтый — повышенная нагрузка, красный — высокая. Данные собираются только пока вкладка открыта.",
     "Resources of the single-board computer used by the program, in real time. Bar colors: green — normal, "
     "yellow — elevated load, red — high. Data is collected only while the tab is open.",
     [
         H("Процессор (CPU)",
           "Нагрузка программы (в процентах одного ядра и всех ядер), всей системы и каждого ядра; ядра, "
           "разрешённые программе, выделены рамкой. График — нагрузка программы за 2 минуты.",
           "Load of the program (as a percentage of one core and of all cores), of the whole system and of each "
           "core; cores allowed for the program are outlined. The graph shows the program load over 2 minutes."),
         H("Нейропроцессор (NPU)",
           "Используется ли NPU, доля его времени, занятая программой, и время выполнения каждой модели. "
           "Загрузка NPU всей системой доступна только с правами администратора.",
           "Whether the NPU is used, the share of its time used by the program and the run time of each model. "
           "The whole-system NPU load is only available with root privileges."),
         H("Оперативная память (RAM)", "Память программы и всей системы, подкачка.",
           "Memory of the program and of the whole system, swap."),
         H("Температура", "Температура датчиков SoC (процессор, NPU, GPU и др.). Выше 85 °C — перегрев.",
           "Temperature of the SoC sensors (CPU, NPU, GPU, etc.). Above 85 °C means overheating."),
         H("Время обработки кадра:",
           "Сколько в среднем занимает анализ одного кадра. Должно быть заметно меньше интервала между кадрами "
           "(200 мс при 5 кадр/с).",
           "Average time to analyze one frame. Must be well below the interval between frames (200 ms at 5 fps)."),
         H("Диск и почта", "Свободное место, объём данных программы, очередь писем и последняя ошибка отправки.",
           "Free space, size of the program data, e-mail queue and the last sending error."),
     ]),
    ("Учётная запись",
     "Администратор программы.",
     "The program administrator.",
     [
         H("Сменить логин/пароль…",
           "Логин и пароль нужны для входа в настройки, приостановки контроля и выхода из программы. Пароль "
           "хранится в виде необратимого хеша. После 5 неудачных попыток вход блокируется на 60 секунд.",
           "The login and password are required to open the settings, pause monitoring and exit the program. "
           "The password is stored as an irreversible hash. After 5 failed attempts login is blocked for 60 "
           "seconds."),
     ]),
]
