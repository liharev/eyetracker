"""Английские переводы строк интерфейса (ключ — исходный русский текст).

Полнота проверяется тестом tests/test_i18n.py; список строк — scripts/i18n_keys.py.
"""

EN = {
    # ------------------------------------------------------------ общее
    "CAMAI бдительность": "CAMAI vigilance",
    "да": "yes",
    "нет": "no",
    "все": "all",
    "Ошибка": "Error",
    "Включено": "Enabled",
    "Автоматически": "Automatic",
    "Удалить": "Delete",
    "Удаление": "Deletion",
    "Сбросить": "Reset",
    "Загрузить…": "Upload…",
    "Проверка": "Check",
    "Состояние": "Status",
    "Состояние:": "Status:",
    "Журнал": "Journal",
    "Отчёт": "Report",
    "Блокировка": "Locking",
    "Калибровка": "Calibration",
    " с": " s",
    " мс": " ms",
    " мин": " min",
    " дн.": " days",
    " кадр/с": " fps",
    " раз/с": " per s",
    "{m} мин": "{m} min",
    "{h} ч {m} мин": "{h} h {m} min",

    # ------------------------------------------------------- категории событий
    "1. Обнаружение человека перед экраном": "1. Person detected in front of the screen",
    "2. Распознавание лиц": "2. Face recognition",
    "3. Блокировка: перед экраном никого нет": "3. Lock: nobody in front of the screen",
    "4. Блокировка: нет авторизованного лица": "4. Lock: no authorized face",
    "5. Блокировка: постороннее лицо": "5. Lock: unknown face",
    "6. Контроль взгляда": "6. Gaze control",
    "Служебные (вход в настройки, ошибки, запуск)": "Service (settings login, errors, startup)",

    # --------------------------------------------------------- события (п.1–6)
    "Перед экраном появился человек (лиц в кадре: {n})": "A person appeared in front of the screen (faces in view: {n})",
    "Перед экраном никого нет": "Nobody in front of the screen",
    "Распознано авторизованное лицо: {name} (сходство {score:.2f})":
        "Authorized face recognized: {name} (similarity {score:.2f})",
    "Обнаружено неизвестное лицо (макс. сходство с базой {score:.2f})":
        "Unknown face detected (max. similarity to the database {score:.2f})",
    "Экран заблокирован: перед экраном никого нет": "Screen locked: nobody in front of the screen",
    "Экран заблокирован: перед экраном нет авторизованного лица":
        "Screen locked: no authorized face in front of the screen",
    "Экран заблокирован: обнаружено постороннее лицо": "Screen locked: an unknown face was detected",
    "норма": "normal",
    "красная рамка": "red frame",
    "мигающая рамка": "blinking frame",
    "звуковой сигнал": "sound alert",
    "Взгляд не на экране {sec:.1f} с — {stage}": "Gaze off the screen for {sec:.1f} s — {stage}",
    "Взгляд авторизованного пользователя не на экране дольше {sec:.0f} с":
        "The authorized user's gaze has been off the screen for more than {sec:.0f} s",
    "Взгляд вернулся на экран": "Gaze returned to the screen",
    "Экран заблокирован — предупреждения о взгляде сняты": "Screen locked — gaze warnings cleared",
    "Авторизованное лицо вне кадра — предупреждения о взгляде сняты":
        "Authorized face out of view — gaze warnings cleared",
    "{text} (взгляд отсутствовал {sec:.1f} с)": "{text} (gaze was away for {sec:.1f} s)",

    # ---------------------------------------------------------- служебные
    "{app} запущен (Qt: {qt})": "{app} started (Qt: {qt})",
    "{app} остановлен": "{app} stopped",
    "Настройки изменены администратором": "Settings changed by the administrator",
    "Заданы учётные данные администратора": "Administrator credentials set",
    "Неудачные попытки входа ({purpose}): {n}": "Failed login attempts ({purpose}): {n}",
    "Вход администратора: {purpose}": "Administrator login: {purpose}",
    "Вход в настройки": "Settings login",
    "Приостановка контроля на {n} мин": "Pause monitoring for {n} min",
    "Контроль приостановлен на {n} мин": "Monitoring paused for {n} min",
    "Контроль возобновлён": "Monitoring resumed",
    "Выход из программы": "Exit the program",
    "В базу авторизованных лиц добавлено лицо": "A face was added to the authorized faces database",
    "Из базы авторизованных лиц удалено лицо «{name}»": "Face “{name}” was removed from the authorized faces database",
    "Журнал событий очищен администратором": "Event journal cleared by the administrator",
    "Учётные данные администратора изменены": "Administrator credentials changed",
    "Не удалось заблокировать экран: нет подходящей команды": "Could not lock the screen: no suitable command",

    # ------------------------------------------------------------- трей
    "Запуск…": "Starting…",
    "Настройки…": "Settings…",
    "Приостановить контроль": "Pause monitoring",
    "на {n} мин": "for {n} min",
    "Возобновить контроль": "Resume monitoring",
    "Выход": "Exit",
    "Ошибка: {msg}": "Error: {msg}",
    "Камера: {msg}": "Camera: {msg}",
    "Пауза ({n} мин)": "Paused ({n} min)",
    "перед экраном никого нет": "nobody in front of the screen",
    "лиц: {n}": "faces: {n}",
    "авторизованы: {names}": "authorized: {names}",
    "посторонних: {n}": "unknown: {n}",
    "взгляд: {state}": "gaze: {state}",
    "на экране": "on screen",
    "не на экране": "off screen",
    "мимо экрана": "off screen",

    # ------------------------------------------------------- движок, камера
    "Камера «{source}» недоступна": "Camera “{source}” is not available",
    "Нет кадров с камеры": "No frames from the camera",
    "нет файлов моделей .rknn (их устанавливает install.sh)": "no .rknn model files (install.sh installs them)",
    "База авторизованных лиц пуста — правила 4, 5, 6 не работают":
        "The authorized faces database is empty — rules 4, 5, 6 are inactive",
    "Нет файлов моделей YuNet/SFace. Запустите: {cmd}": "YuNet/SFace model files are missing. Run: {cmd}",
    "Посторонний {score:.2f}": "Unknown {score:.2f}",
    "далеко": "too far",
    "МИМО": "OFF",
    "Взгляд: yaw {yaw:+.0f}° pitch {pitch:+.0f}° — {state}": "Gaze: yaw {yaw:+.0f}° pitch {pitch:+.0f}° — {state}",
    " (глаза закрыты)": " (eyes closed)",
    "радужка": "iris",
    "Недостаточно точек калибровки": "Not enough calibration points",

    # ------------------------------------------------------------- NPU
    "готов": "ready",
    "NPU Rockchip доступен только на ARM64 (RK3588)": "The Rockchip NPU is only available on ARM64 (RK3588)",
    "не найдена librknnrt.so (её устанавливает install.sh)": "librknnrt.so not found (install.sh installs it)",
    "{what}: код ошибки {code}": "{what}: error code {code}",
    "не ARM64 — NPU Rockchip недоступен": "not ARM64 — the Rockchip NPU is unavailable",
    "устройство NPU (драйвер rknpu) не найдено": "NPU device (rknpu driver) not found",

    # ------------------------------------------------------- пароли, база лиц
    "Логин не может быть пустым": "The login cannot be empty",
    "Пароль должен содержать не менее 4 символов": "The password must be at least 4 characters long",
    "Неверный логин или пароль.": "Wrong login or password.",
    "Слишком много неудачных попыток. Повторите через {sec} с.": "Too many failed attempts. Try again in {sec} s.",
    "Неверный логин или пароль. Вход заблокирован на {sec} с.": "Wrong login or password. Login is blocked for {sec} s.",
    "Имя не может быть пустым": "The name cannot be empty",
    "Нет образцов лица": "No face samples",

    # ----------------------------------------------------------- звуки
    "Короткий сигнал (3 гудка)": "Short beep (3 tones)",
    "Двухтональный звонок": "Two-tone chime",
    "Сирена": "Siren",
    "Свой: {name}": "Custom: {name}",
    "Неподдерживаемый формат. Допустимо: {formats}": "Unsupported format. Allowed: {formats}",
    "Встроенные сигналы удалить нельзя": "Built-in sounds cannot be deleted",

    # ------------------------------------------------------- модели
    "Получен слишком маленький файл для {name} — проверьте доступ к сети":
        "The downloaded {name} file is too small — check network access",
    "Контрольная сумма {name} не совпадает ({digest})": "Checksum of {name} does not match ({digest})",

    # ------------------------------------------------------ почта и журнал
    "время": "time",
    "категория": "category",
    "тип": "type",
    "сообщение": "message",
    "подробности": "details",
    "снимок": "snapshot",
    "Компьютер: {host}": "Computer: {host}",
    "Время: {value}": "Time: {value}",
    "Категория: {value}": "Category: {value}",
    "Событие: {value}": "Event: {value}",
    "Подробности: {value}": "Details: {value}",
    "Отчёт {app} о событиях": "{app} event report",
    "Период: {start} — {end}": "Period: {start} — {end}",
    "Всего событий: {n}": "Total events: {n}",
    "Отчёт о событиях ({n})": "Event report ({n})",
    "Не настроен SMTP-сервер или адрес получателя": "SMTP server or recipient address is not configured",
    "... и ещё {n} (см. вложение CSV)": "... and {n} more (see the CSV attachment)",
    "Отчёт отправлен ({n} событий)": "Report sent ({n} events)",
    "Неверное время: {value}": "Invalid time: {value}",
    "Новых событий нет — отчёт не отправлялся": "No new events — the report was not sent",
    "SMTP не настроен — события сохранены и будут отправлены позже":
        "SMTP is not configured — events are kept and will be sent later",
    "Ошибка отправки: {error}": "Sending error: {error}",

    # ------------------------------------------------------- самопроверка
    "Камеры:": "Cameras:",
    "Команды блокировки:": "Lock commands:",
    "Состояние блокировки определяется:": "Lock state detection:",
    "Проигрыватели звука:": "Sound players:",
    "Энергоэффективные ядра:": "Efficiency cores:",
    "Сеанс:": "Session:",
    "LiteRT {v}: модель точек лица выполняется через LiteRT (быстрее)":
        "LiteRT {v}: the face landmark model runs on LiteRT (faster)",
    "Модель {key}: {path}": "Model {key}: {path}",
    "NPU RK3588: {why}; модели .rknn: {n} из 4": "RK3588 NPU: {why}; .rknn models: {n} of 4",
    "не найдены": "not found",
    "система однородная": "homogeneous system",
    "OpenCV: НЕ УСТАНОВЛЕН": "OpenCV: NOT INSTALLED",
    "LiteRT: нет — модель точек лица будет выполняться через OpenCV DNN (медленнее, но работает)":
        "LiteRT: no — the face landmark model will run on OpenCV DNN (slower, but works)",
    "Qt: НЕ УСТАНОВЛЕН (нужен python3-pyqt5 или PySide6)": "Qt: NOT INSTALLED (python3-pyqt5 or PySide6 is required)",
    " — нейросети будут выполняться на NPU": " — neural networks will run on the NPU",
    "нет (python3 -m eyetracker --download-models)": "missing (python3 -m eyetracker --download-models)",
    "[есть]   {key}: {path}": "[found]  {key}: {path}",
    "[готово] {key}: {path}": "[done]   {key}: {path}",
    "[ошибка] {key}: {error}": "[error]  {key}: {error}",
    "открыть настройки (в т.ч. у запущенного экземпляра)": "open the settings (also of a running instance)",
    "загрузить модели нейросетей и выйти": "download the neural network models and exit",
    "проверить окружение и выйти": "check the environment and exit",
    "обновить значки и пункт меню и выйти": "update the icons and the menu entry and exit",
    "не загружать модели автоматически": "do not download models automatically",
    "подробный журнал": "verbose log",

    # ------------------------------------------------------- калибровка
    "Калибровка отменена": "Calibration cancelled",
    "Не удалось определить взгляд: лицо не найдено или плохо освещено. Сядьте перед камерой и повторите.":
        "Could not determine the gaze: the face was not found or is poorly lit. Sit in front of the camera "
        "and try again.",
    "Калибровка взгляда\n\nСядьте в обычное рабочее положение.\n"
    "Смотрите на появляющиеся точки (только глазами и головой — как при работе).\nEsc — отмена.":
        "Gaze calibration\n\nSit in your usual working position.\n"
        "Look at the dots as they appear (with your eyes and head, as when working).\nEsc — cancel.",
    "Точка {i} из {n}": "Point {i} of {n}",

    # ------------------------------------------------------- вход в настройки
    "{app} — вход": "{app} — login",
    "Логин:": "Login:",
    "Пароль:": "Password:",
    "{app} — учётная запись администратора": "{app} — administrator account",
    "Новый пароль:": "New password:",
    "Повтор пароля:": "Repeat password:",
    "Первый запуск: задайте логин и пароль для входа в настройки. "
    "Без них изменить настройки и закрыть программу будет нельзя.":
        "First start: set a login and password for the settings. "
        "Without them it will not be possible to change the settings or close the program.",
    "Пароли не совпадают": "Passwords do not match",

    # ------------------------------------------------------- добавление лица
    "Лицо не найдено": "No face found",
    "В кадре несколько лиц — должен быть только один человек": "Several faces in view — there must be only one person",
    "Лицо слишком мелкое — подойдите ближе к камере": "The face is too small — move closer to the camera",
    "Нет изображения с камеры": "No camera image",
    "Не удалось открыть изображение": "Could not open the image",
    "Имя (ФИО):": "Name:",
    "Снять с камеры ({n} образцов)": "Capture from camera ({n} samples)",
    "Загрузить фото…": "Upload photos…",
    "Фотографии лица": "Face photos",
    "Изображения": "Images",
    "Добавление образцов: {name}": "Adding samples: {name}",
    "Новое авторизованное лицо": "New authorized face",
    "Сядьте перед экраном так, как обычно работаете. Во время съёмки медленно "
    "поворачивайте голову немного влево/вправо/вверх/вниз. В кадре должен быть "
    "только один человек. Можно также загрузить несколько фотографий.":
        "Sit in front of the screen as you usually work. While capturing, slowly turn your head a little "
        "left/right/up/down. Only one person must be in view. You can also upload several photos.",
    "Часть файлов не обработана": "Some files were not processed",
    "Образец {n} снят": "Sample {n} captured",
    "Съёмка завершена": "Capture complete",
    "Проверка образцов": "Sample check",
    "Образцы сильно отличаются друг от друга (возможно, в кадр попали разные люди). Всё равно сохранить?":
        "The samples differ a lot from each other (perhaps different people were in view). Save anyway?",
    "Похожее лицо уже есть": "A similar face already exists",
    "Образцы похожи на «{name}» (сходство {score:.2f}). Всё равно сохранить?":
        "The samples look like “{name}” (similarity {score:.2f}). Save anyway?",

    # ------------------------------------------------------- окно настроек
    "{app} — настройки": "{app} — settings",
    "Общие": "General",
    "Камера": "Camera",
    "База лиц": "Faces",
    "Взгляд": "Gaze",
    "Уведомления": "Notifications",
    "Диагностика": "Diagnostics",
    "Учётная запись": "Account",

    "Интерфейс и запуск": "Interface and startup",
    "Язык интерфейса:": "Interface language:",
    "Как в системе": "System default",
    "Значок в трее:": "Tray icon:",
    "Автоматически (по теме оформления)": "Automatic (follow the theme)",
    "Светлый": "Light",
    "Тёмный": "Dark",
    "Запускать автоматически при входе в систему": "Start automatically at login",
    "Нагрузка на систему": "System load",
    "Нейросети выполнять на:": "Run neural networks on:",
    "Автоматически (NPU, если доступен)": "Automatic (NPU if available)",
    "Только процессор (CPU)": "Processor only (CPU)",
    "Ядро NPU:": "NPU core:",
    "Ядро 0": "Core 0",
    "Ядро 1": "Core 1",
    "Ядро 2": "Core 2",
    "Частота анализа (есть люди):": "Analysis rate (people present):",
    "Частота анализа (никого нет):": "Analysis rate (nobody present):",
    "Ширина кадра для детектора (CPU):": "Detector frame width (CPU):",
    "Ядра CPU:": "CPU cores:",
    "Приоритет (nice):": "Priority (nice):",
    "Полный просмотр кадра каждые:": "Full-frame scan every:",
    "Оценка взгляда (без предупреждения):": "Gaze estimation (no warning):",
    "Точная оценка взгляда по радужке (модель точек лица)": "Precise iris-based gaze estimation (face landmark model)",
    "NPU — нейропроцессор RK3588: поиск, распознавание лиц и оценка взгляда выполняются "
    "на нём, а не на процессоре. Если NPU недоступен, программа сама работает на CPU.":
        "NPU is the RK3588 neural processor: face detection, recognition and gaze estimation run on it "
        "instead of the CPU. If the NPU is unavailable, the program automatically uses the CPU.",
    "«auto» — только энергоэффективные ядра (на RK3588: A55, cpu0-3), производительные "
    "ядра A76 остаются другим программам. Пусто — без ограничения. Ядра и приоритет "
    "применяются после перезапуска программы. Между полными просмотрами кадра лицо ищется "
    "только возле уже найденных лиц; новое лицо будет замечено не позже, чем через этот "
    "интервал. Пока рамки нет, взгляд оценивается реже; при появлении рамки — на каждом "
    "кадре, чтобы она сразу исчезала при возврате взгляда.":
        "“auto” — efficiency cores only (on RK3588: A55, cpu0-3); the performance A76 cores remain for other "
        "programs. Empty — no restriction. Cores and priority take effect after restarting the program. "
        "Between full-frame scans, faces are searched only near already found faces; a new face is noticed "
        "within this interval. While there is no frame, the gaze is estimated less often; once the frame "
        "appears — on every frame, so that it disappears as soon as the gaze returns.",
    "Хранить события:": "Keep events for:",
    "0 — хранить бессрочно.": "0 — keep forever.",

    "Источник:": "Source:",
    "Драйвер:": "Driver:",
    "Ширина:": "Width:",
    "Высота:": "Height:",
    "Частота захвата:": "Capture rate:",
    "Поворот:": "Rotation:",
    "Зеркально": "Mirror",
    "Источник: номер камеры (0), устройство (/dev/video0) или конвейер GStreamer "
    "(для MIPI-камеры RK3588). Изменения вступают в силу по кнопке «Применить».":
        "Source: camera number (0), device (/dev/video0) or a GStreamer pipeline (for an RK3588 MIPI camera). "
        "Changes take effect after pressing “Apply”.",
    "Обработка: {fps:.1f} кадр/с · нейросети: {acc} · лиц: {faces} · оценка взгляда: {gaze}":
        "Processing: {fps:.1f} fps · neural networks: {acc} · faces: {faces} · gaze estimation: {gaze}",

    "Добавить лицо…": "Add face…",
    "Добавить образцы…": "Add samples…",
    "Переименовать…": "Rename…",
    "Переименовать": "Rename",
    "Имя:": "Name:",
    "Распознавание": "Recognition",
    "Порог сходства лица:": "Face similarity threshold:",
    "Порог детектора лиц:": "Face detector threshold:",
    "Мин. размер лица для распознавания:": "Min. face size for recognition:",
    "Перепроверка известных лиц каждые:": "Re-check known faces every:",
    "Порог сходства: выше — строже (меньше ложных «своих», но чаще «посторонний»). "
    "Рекомендуется 0.36–0.45. Лица мельче минимального размера учитываются только "
    "как присутствие человека.":
        "Similarity threshold: higher is stricter (fewer false matches, but more “unknown”). "
        "0.36–0.45 is recommended. Faces smaller than the minimum size only count as a person's presence.",
    "{name}  (образцов: {n})": "{name}  (samples: {n})",
    "Модели распознавания не загружены.": "Recognition models are not loaded.",
    "Удалить «{name}» из базы?": "Delete “{name}” from the database?",

    "1. Обнаружение человека": "1. Person detection",
    "Человек считается ушедшим через:": "A person is considered gone after:",
    "3. Блокировка, если перед экраном никого нет": "3. Lock if nobody is in front of the screen",
    "Таймаут:": "Timeout:",
    "4. Блокировка, если нет авторизованного лица (даже при наличии других)":
        "4. Lock if there is no authorized face (even if others are present)",
    "5. Блокировка при появлении постороннего лица (даже рядом с авторизованным)":
        "5. Lock when an unknown face appears (even next to an authorized one)",
    "Время подтверждения:": "Confirmation time:",
    "Постороннее лицо должно быть видно указанное время — это защищает от ложных "
    "срабатываний. Пункты 4 и 5 работают, только если база лиц не пуста.":
        "An unknown face must be visible for this time — this prevents false alarms. "
        "Rules 4 and 5 work only if the faces database is not empty.",
    "Способ блокировки": "Locking method",
    "Метод:": "Method:",
    "Автоматически (loginctl / D-Bus / xflock4 / …)": "Automatic (loginctl / D-Bus / xflock4 / …)",
    "Своя команда": "Custom command",
    "Команда:": "Command:",
    "например: loginctl lock-session": "e.g.: loginctl lock-session",
    "Повторная блокировка через:": "Re-lock after:",
    "Проверить блокировку сейчас": "Test locking now",
    "Повторная блокировка выполняется, если после разблокировки условие "
    "по-прежнему выполняется (и окружение сообщает состояние блокировки).":
        "The screen is locked again if the condition still holds after unlocking "
        "(and the desktop reports the lock state).",
    "Заблокировать экран сейчас?": "Lock the screen now?",
    "Команда блокировки выполнена успешно.": "The lock command completed successfully.",
    "Не найдено работающей команды блокировки — укажите свою команду.":
        "No working lock command found — specify a custom command.",

    "6. Контроль взгляда авторизованного лица": "6. Gaze control of the authorized face",
    "Красная рамка через:": "Red frame after:",
    "Мигающая рамка через:": "Blinking frame after:",
    "Звуковой сигнал через:": "Sound alert after:",
    "Уведомление на e-mail через:": "E-mail notification after:",
    "Недоступно: включите «E-mail сразу» для событий контроля взгляда на вкладке «Уведомления».":
        "Unavailable: enable “E-mail immediately” for gaze control events on the “Notifications” tab.",
    "Время отсчитывается с момента, когда взгляд ушёл с экрана; мигание включается не "
    "раньше красной рамки, а звук — не раньше мигания. При возвращении взгляда таймеры "
    "сбрасываются, рамка и звук отключаются.":
        "Time is counted from the moment the gaze leaves the screen; blinking starts no earlier than the red "
        "frame, and sound no earlier than blinking. When the gaze returns, the timers are reset and the frame "
        "and sound are turned off.",
    "Взгляд считается вернувшимся через:": "Gaze is considered returned after:",
    "Пропажа лица из кадра (отвернулся) = взгляд не на экране": "Face lost from view (turned away) = gaze off screen",
    "Закрытые глаза = взгляд не на экране": "Closed eyes = gaze off screen",
    "Зона экрана (градусы относительно направления на камеру)": "Screen zone (degrees relative to the camera direction)",
    "По горизонтали от:": "Horizontal from:",
    "По горизонтали до:": "Horizontal to:",
    "По вертикали от (вниз):": "Vertical from (down):",
    "По вертикали до (вверх):": "Vertical to (up):",
    "Допуск:": "Tolerance:",
    "Коэффициент поворота глаз:": "Eye rotation factor:",
    "Калибровать…": "Calibrate…",
    "Сбросить к значениям по умолчанию": "Reset to defaults",
    "Сейчас:": "Now:",
    "Камера расположена по центру верхней кромки, поэтому при взгляде на экран угол "
    "по вертикали отрицательный. Калибровка (5 точек) настраивает зону под конкретного "
    "пользователя и монитор — выполните её сидя в обычном рабочем положении.":
        "The camera is at the center of the top edge, so the vertical angle is negative when looking at the "
        "screen. Calibration (5 points) adjusts the zone to the specific user and monitor — do it sitting in "
        "your usual working position.",
    "Зона откалибрована": "Zone calibrated",
    "Калибровка не выполнялась (используются значения по умолчанию)": "Not calibrated (default values are used)",
    "Камера не работает или контроль приостановлен.": "The camera is not working or monitoring is paused.",
    "Калибровка не выполнена": "Calibration failed",
    "Зона экрана: по горизонтали {y1:+.0f}…{y2:+.0f}°, по вертикали {p1:+.0f}…{p2:+.0f}°.\nНажмите «Применить».":
        "Screen zone: horizontal {y1:+.0f}…{y2:+.0f}°, vertical {p1:+.0f}…{p2:+.0f}°.\nPress “Apply”.",
    "по горизонтали {yaw:+.1f}°, по вертикали {pitch:+.1f}° — {where}{closed}; стадия: {stage}":
        "horizontal {yaw:+.1f}°, vertical {pitch:+.1f}° — {where}{closed}; stage: {stage}",
    "Рамка": "Frame",
    "Толщина:": "Thickness:",
    "Цвет:": "Color:",
    "Цвет рамки": "Frame color",
    "Период мигания:": "Blink period:",
    "Показать рамку": "Show frame",
    "Мигающая": "Blinking",
    "Скрыть": "Hide",
    "Звуковой сигнал": "Sound alert",
    "Сигнал:": "Sound:",
    "Пауза между повторами:": "Pause between repeats:",
    "Громкость:": "Volume:",
    "Свои сигналы: WAV, OGG, MP3, FLAC (для MP3 нужен ffplay или mpv).":
        "Custom sounds: WAV, OGG, MP3, FLAC (MP3 requires ffplay or mpv).",
    "Звуковой файл": "Sound file",
    "Звук": "Sound",

    "Куда направлять события": "Where to send events",
    "Событие": "Event",
    "E-mail сразу": "E-mail immediately",
    "В журнал": "To journal",
    "Журнал + e-mail по расписанию": "Journal + scheduled e-mail",
    "Для контроля взгляда «E-mail сразу» означает одно письмо, если взгляд не на экране "
    "дольше времени, заданного на вкладке «Взгляд» («Уведомление на e-mail через»).":
        "For gaze control, “E-mail immediately” means one e-mail when the gaze stays off the screen longer than "
        "the time set on the “Gaze” tab (“E-mail notification after”).",
    "Сохранять снимок с камеры для событий в журнале": "Save a camera snapshot for journal events",
    "Почтовый сервер (SMTP)": "Mail server (SMTP)",
    "Сервер:": "Server:",
    "Порт:": "Port:",
    "Шифрование:": "Encryption:",
    "Без шифрования": "No encryption",
    "Отправитель:": "Sender:",
    "Получатель(и):": "Recipient(s):",
    "Префикс темы:": "Subject prefix:",
    "Прикладывать снимок с камеры к письму": "Attach a camera snapshot to the e-mail",
    "Отправить тестовое письмо": "Send a test e-mail",
    "Тестовое письмо": "Test e-mail",
    "Это тестовое письмо программы {app}.": "This is a test e-mail from {app}.",
    "Письмо отправлено. Проверьте почтовый ящик.": "The e-mail has been sent. Check your mailbox.",
    "Отчёт по расписанию": "Scheduled report",
    "Расписание:": "Schedule:",
    "Каждые N минут": "Every N minutes",
    "Ежедневно в указанное время": "Daily at the specified times",
    "Интервал:": "Interval:",
    "Время (ЧЧ:ММ через запятую):": "Times (HH:MM, comma-separated):",
    "Отправлять отчёт, даже если новых событий нет": "Send the report even if there are no new events",
    "Следующий отчёт:": "Next report:",
    "Отправить отчёт сейчас": "Send the report now",

    "Все события": "All events",
    "Обновить": "Refresh",
    "Экспорт CSV…": "Export CSV…",
    "Очистить…": "Clear…",
    "Время": "Time",
    "Категория": "Category",
    "Двойной щелчок — открыть снимок с камеры (если сохранён). Показаны последние 2000 событий.":
        "Double-click to open the camera snapshot (if saved). The last 2000 events are shown.",
    "Есть снимок — двойной щелчок": "Snapshot available — double-click",
    "Экспорт журнала": "Export journal",
    "Удалить все события из журнала?": "Delete all events from the journal?",

    "Администратор": "Administrator",
    "Сменить логин/пароль…": "Change login/password…",
    "Логин и пароль требуются для входа в настройки, приостановки контроля и выхода "
    "из программы. Пароль хранится в виде хеша PBKDF2-SHA256.":
        "The login and password are required to open the settings, pause monitoring and exit the program. "
        "The password is stored as a PBKDF2-SHA256 hash.",
    "Логин и пароль изменены.": "Login and password changed.",

    "Мигающая рамка не может включаться раньше красной, а звуковой сигнал — раньше мигающей рамки.":
        "The blinking frame cannot start before the red frame, and the sound alert cannot start before the "
        "blinking frame.",
    "Не указано время отчёта.": "The report time is not specified.",
    "Не указана своя команда блокировки.": "The custom lock command is not specified.",
    "Для отправки событий по e-mail укажите SMTP-сервер и получателя "
    "(до этого события по расписанию будут накапливаться в журнале).":
        "To send events by e-mail, specify the SMTP server and recipient "
        "(until then scheduled events will accumulate in the journal).",
    "E-mail не настроен": "E-mail is not configured",
    "Проверьте настройки": "Check the settings",

    # ---------------------------------------------------- диагностика
    "повышенная нагрузка": "elevated load",
    "высокая нагрузка": "high load",
    "Общее состояние": "Overall status",
    "Процессор (CPU)": "Processor (CPU)",
    "Программа:": "Program:",
    "Вся система:": "Whole system:",
    "Программа, 2 мин:": "Program, 2 min:",
    "Ядра:": "Cores:",
    "Нейропроцессор (NPU)": "Neural processor (NPU)",
    "Занятость NPU программой:": "NPU time used by the program:",
    "Загрузка NPU (вся система):": "NPU load (whole system):",
    "Оперативная память (RAM)": "Memory (RAM)",
    "Подкачка (swap):": "Swap:",
    "Температура": "Temperature",
    "Датчики температуры недоступны": "Temperature sensors are unavailable",
    "Камера и обработка": "Camera and processing",
    "Камера:": "Camera:",
    "Время обработки кадра:": "Frame processing time:",
    "Диск и почта": "Disk and mail",
    "Свободно на диске:": "Free disk space:",
    "Почта:": "Mail:",
    "Цвет: зелёный — норма, жёлтый — повышенная нагрузка, красный — высокая. "
    "Данные обновляются раз в секунду, пока открыта эта вкладка.":
        "Color: green — normal, yellow — elevated load, red — high. "
        "Data is updated once per second while this tab is open.",
    "{v:.1f}% одного ядра ({t:.1f}% всех ядер)": "{v:.1f}% of one core ({t:.1f}% of all cores)",
    "Потоков: {threads}; приоритет (nice): {nice}; программе разрешены ядра: {cores}":
        "Threads: {threads}; priority (nice): {nice}; cores allowed for the program: {cores}",
    " (программе не разрешено)": " (not allowed for the program)",
    "используется — нейросети выполняются на NPU": "in use — neural networks run on the NPU",
    "доступен, но не используется (в настройках выбран CPU или ошибка: {err})":
        "available but not used (CPU selected in the settings or error: {err})",
    "недоступен — нейросети выполняются на CPU ({why})": "unavailable — neural networks run on the CPU ({why})",
    "нет NPU": "no NPU",
    "недоступно без прав администратора": "unavailable without root privileges",
    "частота NPU: {f} МГц": "NPU frequency: {f} MHz",
    "время вызова: {items}": "call time: {items}",
    "{mb:.0f} МБ": "{mb:.0f} MB",
    "{p:.0f}% из {gb:.1f} ГБ": "{p:.0f}% of {gb:.1f} GB",
    "{used:.0f} из {total:.0f} МБ": "{used:.0f} of {total:.0f} MB",
    "работает: {fps:.1f} кадр/с с камеры, анализ {afps:.1f} кадр/с":
        "working: {fps:.1f} fps from the camera, analysis {afps:.1f} fps",
    "{ms:.1f} мс": "{ms:.1f} ms",
    "Нейросети: {acc}; оценка взгляда: {gaze}; лиц в кадре: {faces}":
        "Neural networks: {acc}; gaze estimation: {gaze}; faces in view: {faces}",
    "{free:.1f} ГБ из {total:.1f} ГБ ({p:.0f}%)": "{free:.1f} GB of {total:.1f} GB ({p:.0f}%)",
    "Данные программы (модели, база лиц, журнал, снимки): {mb:.0f} МБ; работает {uptime}":
        "Program data (models, faces, journal, snapshots): {mb:.0f} MB; running for {uptime}",
    "в очереди писем: {n}; последняя ошибка: {err}": "e-mails queued: {n}; last error: {err}",
    "макс. {value:.1f}": "max {value:.1f}",
}
