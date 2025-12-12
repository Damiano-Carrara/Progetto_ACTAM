import io
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

class ReportGenerator:
    def __init__(self):
        print("📊 Report Generator Inizializzato")

    def generate_excel(self, playlist, metadata=None):
        """
        Genera un file Excel in memoria (BytesIO) pronto per il download.
        Formatta le colonne stile 'Borderò SIAE' (Senza durata).
        """
        wb = Workbook()
        ws = wb.active
        ws.title = "Programma Musicale"

        # --- INTESTAZIONE ---
        # Definiamo gli stili
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="4F81BD", end_color="4F81BD", fill_type="solid")
        center_align = Alignment(horizontal="center", vertical="center")
        left_align = Alignment(horizontal="left", vertical="center")
        thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), 
                             top=Side(style='thin'), bottom=Side(style='thin'))

        # Intestazioni colonne (Rimosso "DURATA")
        headers = ["N.", "TITOLO OPERA", "COMPOSITORE / AUTORE", "ARTISTA ESECUTORE"]
        
        # Scriviamo gli header nella riga 1
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_align
            cell.border = thin_border

        # --- DATI ---
        row_num = 2
        index_display = 1  # numerazione continua solo sui brani confermati
        for song in playlist:
            # Filtriamo solo le canzoni "Confermate"
            if not song.get('confirmed', False):
                continue

            # Recupero dati e pulizia
            title = song.get('title', '').strip().upper()
            composer = song.get('composer', '').strip().upper()
            artist = song.get('artist', '').strip().title()

            # Scrittura celle
            # Colonna 1: Numero
            ws.cell(row=row_num, column=1, value=index_display).alignment = center_align
            
            # Colonna 2: Titolo
            ws.cell(row=row_num, column=2, value=title).alignment = left_align
            
            # Colonna 3: Compositore
            ws.cell(row=row_num, column=3, value=composer).alignment = left_align
            
            # Colonna 4: Artista
            ws.cell(row=row_num, column=4, value=artist).alignment = left_align
            
            # Applica bordi a tutta la riga
            for c in range(1, 5):
                ws.cell(row=row_num, column=c).border = thin_border

            row_num += 1
            index_display += 1

        # --- FORMATTAZIONE LARGHEZZA COLONNE ---
        ws.column_dimensions['A'].width = 5   # N.
        ws.column_dimensions['B'].width = 45  # Titolo (un po' più largo)
        ws.column_dimensions['C'].width = 40  # Compositore (un po' più largo)
        ws.column_dimensions['D'].width = 30  # Artista

        # --- METADATI AGGIUNTIVI (A piè di pagina) ---
        footer_row = row_num + 2
        
        info_text = f"Generato automaticamente il {datetime.now().strftime('%d/%m/%Y alle %H:%M')}"
        if metadata and 'artist' in metadata:
             info_text += f" - Evento: {metadata['artist']}"
             
        ws.cell(row=footer_row, column=2, value=info_text).font = Font(italic=True, size=9, color="555555")

        # --- SALVATAGGIO IN MEMORIA ---
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        return output

    # ---------- PDF UFFICIALE (stessi dati dell'Excel) ----------
    def generate_pdf_official(self, playlist, metadata=None):
        """
        PDF 'ufficiale': stessi dati del borderò Excel
        (solo brani confermati, con valori eventualmente modificati dall'utente).
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        # Titolo
        story.append(Paragraph("Programma Musicale - Borderò ufficiale", styles["Title"]))
        subtitle = "Elenco dei brani confermati."
        if metadata and "artist" in metadata:
            subtitle += f" Evento: {metadata['artist']}."
        story.append(Paragraph(subtitle, styles["Normal"]))
        story.append(Spacer(1, 12))

        # Tabella
        data = [["N.", "Titolo opera", "Compositore / Autore", "Artista esecutore"]]

        idx = 1
        for song in playlist:
            if not song.get("confirmed", False):
                continue

            title = (song.get("title") or "").strip()
            composer = (song.get("composer") or "").strip()
            artist = (song.get("artist") or "").strip()

            data.append([str(idx), title, composer, artist])
            idx += 1

        if len(data) == 1:
            data.append(["—", "Nessun brano confermato", "", ""])

        table = Table(
            data,
            colWidths=[25, 210, 170, 120],
            repeatRows=1
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F81BD")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (1, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))

        story.append(table)
        story.append(Spacer(1, 12))

        # Footer
        info_text = f"Generato automaticamente il {datetime.now().strftime('%d/%m/%Y alle %H:%M')}"
        if metadata and "artist" in metadata:
            info_text += f" - Evento: {metadata['artist']}"
        story.append(Paragraph(info_text, styles["Italic"]))

        doc.build(story)
        buffer.seek(0)
        return buffer

    # ---------- PDF LOG RAW (dati riconosciuti) ----------
    def generate_pdf_raw(self, playlist, metadata=None):
        """
        PDF 'log riconosciuto':
        dati originali riconosciuti dall'app (original_*), senza modifiche utente in page 3.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph("Log brani riconosciuti - Snapshot tecnico", styles["Title"]))
        subtitle = "Dati originali riconosciuti dal sistema (prima di eventuali modifiche in review)."
        if metadata and "artist" in metadata:
            subtitle += f" Evento: {metadata['artist']}."
        story.append(Paragraph(subtitle, styles["Normal"]))
        story.append(Spacer(1, 12))

        data = [["N.", "Titolo (riconosciuto)", "Compositore (riconosciuto)",
                 "Artista (riconosciuto)", "Confermato", "Ora"]]

        if not playlist:
            data.append(["—", "Nessun brano rilevato", "", "", "", ""])
        else:
            for i, song in enumerate(playlist, 1):
                title = (song.get("original_title") or song.get("title") or "").strip()
                composer = (song.get("original_composer") or song.get("composer") or "").strip()
                artist = (song.get("original_artist") or song.get("artist") or "").strip()
                confirmed = "Sì" if song.get("confirmed") else "No"
                timestamp = song.get("timestamp") or ""

                data.append([str(i), title, composer, artist, confirmed, timestamp])

        table = Table(
            data,
            colWidths=[22, 170, 150, 130, 55, 50],
            repeatRows=1
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (1, 0), (-2, -1), "LEFT"),
            ("ALIGN", (-1, 1), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))

        story.append(table)
        story.append(Spacer(1, 12))

        info_text = f"Snapshot generato il {datetime.now().strftime('%d/%m/%Y alle %H:%M')}"
        story.append(Paragraph(info_text, styles["Italic"]))

        doc.build(story)
        buffer.seek(0)
        return buffer
