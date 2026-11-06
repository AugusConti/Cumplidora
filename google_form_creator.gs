/**
 * Generador automático en 1 clic del Formulario de Google + Planilla para Cumplidora.
 *
 * Cómo usarlo (toma 1 minuto):
 * 1. Entrá a https://script.google.com y tocá "Nuevo proyecto".
 * 2. Borrá lo que haya y pegá todo este código.
 * 3. Arriba tocá "Ejecutar" (te va a pedir permisos en tu propia cuenta: "Revisar permisos" -> Avanzado -> Ir a Proyecto).
 * 4. Abajo en el "Registro de ejecución" te van a aparecer los 2 links listos:
 *    - El link del Formulario para guardar como ícono en la pantalla principal de tu celu.
 *    - El link de la Planilla para hacer: Archivo -> Compartir -> Publicar en la web -> Valores separados por comas (.csv).
 */
function crearFormularioCumplidora() {
  const form = FormApp.create("🎂 Cumplidora - Nuevo Cumpleaños");
  form.setDescription(
    "Cargá un cumpleaños sin importar el año. Si dejás 'Avisos' sin marcar, te avisa por defecto una semana antes, el día anterior y el mismo día."
  );
  form.setConfirmationMessage("✅ ¡Cumpleaños guardado! Tu PC lo sincronizará automáticamente.");

  // 1. Nombre
  form.addTextItem()
    .setTitle("Nombre")
    .setHelpText("Ej: Juan Pérez")
    .setRequired(true);

  // 2. Día (1 a 31)
  const dayValidation = FormApp.createTextValidation()
    .setHelpText("Ingresá un día válido entre 1 y 31")
    .requireNumberBetween(1, 31)
    .build();
  form.addTextItem()
    .setTitle("Día")
    .setValidation(dayValidation)
    .setRequired(true);

  // 3. Mes
  form.addListItem()
    .setTitle("Mes")
    .setChoiceValues([
      "01 - Enero",
      "02 - Febrero",
      "03 - Marzo",
      "04 - Abril",
      "05 - Mayo",
      "06 - Junio",
      "07 - Julio",
      "08 - Agosto",
      "09 - Septiembre",
      "10 - Octubre",
      "11 - Noviembre",
      "12 - Diciembre",
    ])
    .setRequired(true);

  // 4. Avisos (casillas de verificación)
  const notifyItem = form.addCheckboxItem()
    .setTitle("Avisos")
    .setHelpText("Elegí cuándo recibir notificación (si no marcás ninguno, se activan los 3).");
  notifyItem.setChoices([
    notifyItem.createChoice("El mismo día"),
    notifyItem.createChoice("El día anterior"),
    notifyItem.createChoice("La semana anterior"),
  ]);

  // 5. Notas opcionales
  form.addTextItem()
    .setTitle("Notas")
    .setHelpText("Opcional: idea de regalo, relación, o escribí BORRAR para dar de baja a esta persona.");

  // Crear y vincular Google Sheet automáticamente
  const ss = SpreadsheetApp.create("Cumplidora - Respuestas");
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());
  SpreadsheetApp.flush();

  // Eliminar la hoja vacía inicial ("Hoja 1") para que la pestaña del formulario sea la única
  const sheets = ss.getSheets();
  if (sheets.length > 1) {
    for (const sh of sheets) {
      if (!sh.getFormUrl() && ss.getSheets().length > 1) {
        ss.deleteSheet(sh);
      }
    }
  }

  Logger.log("==========================================");
  Logger.log("✅ ¡CREADO CON ÉXITO!");
  Logger.log("📱 LINK DEL FORMULARIO (para tu celular): " + form.getPublishedUrl());
  Logger.log("📊 LINK DE LA PLANILLA (Google Sheets):   " + ss.getUrl());
  Logger.log("==========================================");
  Logger.log("Último paso en la Planilla: abrí el link de Google Sheets -> Archivo -> Compartir -> Publicar en la web -> elegí 'Valores separados por comas (.csv)' -> Publicar y copiá ese link para Cumplidora.");
}
