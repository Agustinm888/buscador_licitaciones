import os
import requests
import time
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google import genai
from dotenv import load_dotenv

# --- 1. Configuración Inicial ---
load_dotenv()  # Carga variables desde un archivo .env si existe

TICKET = os.environ.get("MERCADO_PUBLICO_TICKET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "tu_correo@gmail.com")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "tu_correo@gmail.com")

# Configurar logging para registrar el proceso
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 2. Búsqueda de Licitaciones ---
def buscar_licitaciones():
    logging.info("Buscando licitaciones de hoy en Mercado Público...")
    fecha_hoy = datetime.now().strftime("%d%m%Y")
    url = f"https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json?fecha={fecha_hoy}&ticket={TICKET}"
    
    try:
        response = requests.get(url, timeout=15) # Evita bloqueos indefinidos
        response.raise_for_status()
        data = response.json()
        
        licitaciones = data.get("Listado", [])
        logging.info(f"Se encontraron {len(licitaciones)} licitaciones en total para hoy.")
        return licitaciones
    except requests.exceptions.RequestException as e:
        logging.error(f"Error al conectar con Mercado Público: {e}")
        return []

# --- 3. Pre-Filtro por Palabras Clave (Optimización) ---
def pre_filtrar_licitaciones(licitaciones):
    """
    Filtra localmente antes de usar la API de Gemini para ahorrar tiempo y tokens.
    """
    palabras_clave = [
        "topografía", "topografico", "geomatica", "geomática", "geomensura",
        "cartografía", "sig ", "gis ", "arcgis", "fotogrametría", "teledetección",
        "levantamiento", "geodesia", "lidar", "gnss", "taquimetría", "civil 3d"
    ]
    
    candidatas = []
    for lic in licitaciones:
        texto_busqueda = f"{lic.get('Nombre', '')} {lic.get('Descripcion', '')}".lower()
        if any(keyword in texto_busqueda for keyword in palabras_clave):
            candidatas.append(lic)
            
    logging.info(f"{len(candidatas)} licitaciones pasaron el pre-filtro de palabras clave.")
    return candidatas

# --- 4. Filtrado Avanzado con IA (Gemini) ---
def filtrar_con_ia(licitaciones_candidatas):
    if not licitaciones_candidatas:
        return []
        
    if not GEMINI_API_KEY:
        logging.warning("No se configuró GEMINI_API_KEY. Se omitirá el filtro IA.")
        return licitaciones_candidatas

    logging.info("Filtrando candidatas con Gemini...")
    client = genai.Client(api_key=GEMINI_API_KEY)
    perfil = "Geomática, Topografía, Geomensura, Cartografía, SIG, Fotogrametría"
    
    licitaciones_filtradas = []
    
    for lic in licitaciones_candidatas:
        titulo = lic.get("Nombre", "Sin título")
        descripcion = lic.get("Descripcion", "")
        
        prompt = f"""
        Actúa como un experto en licitaciones de ingeniería y geociencias en Chile.
        Evalúa si la siguiente licitación es estrictamente relevante para una empresa que ofrece servicios de: {perfil}.
        
        Título: {titulo}
        Descripción: {descripcion}
        
        Responde ÚNICAMENTE con "SI" si es un servicio que esta empresa podría postular, o "NO" si es irrelevante (por ejemplo, si solo compran software genérico o materiales de construcción sin relación).
        """
        
        try:
            # Uso de flash para respuestas rápidas y económicas
            response = client.models.generate_content(
                model='gemini-2.5-flash', 
                contents=prompt
            )
            
            respuesta_texto = response.text.strip().upper()
            
            if "SI" in respuesta_texto:
                logging.info(f"✅ ACEPTADA por IA: {titulo}")
                licitaciones_filtradas.append(lic)
            else:
                logging.info(f"❌ Descartada por IA: {titulo}")
                
        except Exception as e:
            logging.error(f"Error con Gemini al procesar '{titulo}': {e}")
            # Si falla la IA, conservamos la licitación por precaución
            licitaciones_filtradas.append(lic)
        
        time.sleep(1.5) # Pausa reducida, pero necesaria para rate limits
        
    return licitaciones_filtradas

# --- 5. Envío de Notificación ---
def enviar_correo(licitaciones_relevantes):
    if not licitaciones_relevantes or not EMAIL_PASSWORD:
        logging.info("Sin licitaciones relevantes o sin credenciales de correo. Omitiendo notificación.")
        return

    logging.info("Enviando correo con los resultados...")
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECIPIENT
    msg['Subject'] = f"🔍 {len(licitaciones_relevantes)} Licitaciones Relevantes en Mercado Público"
    
    cuerpo = """
    <h2>Licitaciones de Geomática y Topografía Encontradas</h2>
    <p>El sistema ha detectado las siguientes oportunidades para hoy:</p>
    <ul>
    """
    
    for lic in licitaciones_relevantes:
        codigo = lic.get('CodigoExterno')
        link = f"https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idLicitacion={codigo}"
        cuerpo += f"<li><strong>{lic.get('Nombre')}</strong> ({codigo}) - <a href='{link}'>Ver detalle</a></li>"
        
    cuerpo += "</ul>"
    msg.attach(MIMEText(cuerpo, 'html'))
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=10) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
        logging.info("¡Correo enviado exitosamente!")
    except Exception as e:
        logging.error(f"Error al enviar el correo: {e}")

# --- 6. Flujo de Ejecución ---
def main():
    licitaciones_hoy = buscar_licitaciones()
    
    if licitaciones_hoy:
        candidatas = pre_filtrar_licitaciones(licitaciones_hoy)
        relevantes = filtrar_con_ia(candidatas)
        
        if relevantes:
            enviar_correo(relevantes)
        else:
            logging.info("El filtro descartó todas las licitaciones. Nada que enviar.")
    else:
        logging.info("No se descargaron licitaciones para procesar hoy.")

if __name__ == "__main__":
    main()
