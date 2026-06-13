# DSSD-2025: Sistema de Gestión y Colaboración de Proyectos para ONGs

Este proyecto es una plataforma web desarrollada para la materia **Desarrollo de Software en Sistemas Distribuidos (DSSD)** de la Facultad de Informática de la Universidad Nacional de La Plata (UNLP). 

El sistema permite a distintas ONGs y al Consejo Directivo registrar, gestionar y monitorear proyectos sociales, coordinar necesidades de colaboración (económica, materiales, mano de obra, etc.) e integrar flujos de procesos de negocio utilizando **Bonita BPM** a través de su API REST.

---

## 🚀 Arquitectura y Tecnologías

El proyecto se basa en una arquitectura cliente-servidor distribuida:
- **Backend / Web Framework**: [Django 5.2](https://www.djangoproject.com/) (Python 3.12).
- **Base de Datos**: [PostgreSQL 16](https://www.postgresql.org/) en contenedor de Docker (desarrollo local configurable a SQLite).
- **Motor de Procesos (BPM)**: [Bonita BPM](https://www.bonitasoft.com/) (integrado mediante API REST para orquestación de procesos).
- **Contenedores**: [Docker](https://www.docker.com/) y [Docker Compose](https://docs.docker.com/compose/) para despliegue automatizado.
- **Servidor Web / Estáticos**: [Gunicorn](https://gunicorn.org/) con [WhiteNoise](http://whitenoise.evans.io/) para servir archivos estáticos eficientemente.

---

## 👥 Roles del Sistema y Funcionalidades

El sistema implementa tres grupos/roles de usuarios con permisos específicos definidos mediante decoradores y la base de datos de Django:

### 1. ONG Solicitante
*   **Creación de Proyectos**: Permite dar de alta un proyecto ingresando nombre, descripción, rango de fechas y una lista dinámica de necesidades de colaboración (`CollaborationRequest`).
*   **Integración de Inicio (Bonita)**: Al crear el proyecto, se inicia automáticamente una instancia del proceso de aprobación en Bonita BPM, seteando las variables de caso (`idProyecto` y `colaboracionesSolicitadas`), asignando y completando de forma transparente la primera tarea (`Crear proyecto en la app`).
*   **Plan de Trabajo**: Permite agregar etapas secuenciales (`Stage`) para detallar la planificación temporal del proyecto.
*   **Resolución de Observaciones**: Si el Consejo Directivo genera observaciones, la ONG Solicitante puede visualizarlas, subsanar los inconvenientes e indicar que la observación ha sido resuelta. Esto avanza el caso correspondiente en Bonita BPM llamando a la tarea `Resolver problemas`.

### 2. ONG Colaboradora
*   **Visualización de Necesidades**: Acceso a un panel centralizado (`/needs/`) que recopila los pedidos de ayuda activos.
*   **Filtrado Avanzado**: Búsqueda por tipo de necesidad (Económica, Materiales, Mano de obra, Otros) y por estado (Abiertas o Completadas).
*   **Formatos Disponibles**: Visualización interactiva en HTML o descarga estructurada en formato JSON (`/needs/?format=json`).

### 3. Consejo Directivo (Administración / Gerencial)
*   **Auditoría y Supervisión**: Acceso al listado completo de proyectos registrados en la plataforma.
*   **Monitoreo de Proyectos**: Habilidad para iniciar el proceso de monitoreo (`start_monitoring`) en Bonita BPM, el cual ejecuta la tarea `Revisión de proyectos` transmitiendo información clave (ID de proyecto, aprobación inicial y correos electrónicos).
*   **Carga de Observaciones**: Permite registrar observaciones (`Observation`) en el proyecto cuando se detectan desviaciones. Esto notifica al proceso BPM mediante la tarea `Enviar informe de sugerencias` y bloquea nuevos reportes de monitoreo hasta su resolución.

---

## 📊 Modelo de Datos (Base de Datos)

El diseño del modelo relacional en [projects/models.py](https://github.com/EzequielReale/DSSD-2025/blob/main/projects/models.py) comprende:

*   **`Project`**: Almacena el nombre del proyecto, fechas, creador, y los identificadores de caso de Bonita (`bonita_case_id` para aprobación y `monitoring_case_id` para monitoreo).
*   **`CollaborationRequest`**: Representa un recurso solicitado (dinero, insumos, etc.). Clasificado por `RequestType` (ECON, MAT, MO, OTRO) y `RequestStatus` (OPEN, RESERVED, COMPLETED).
*   **`Commitment`**: Vincula las intenciones de colaboración de terceros con solicitudes específicas.
*   **`Stage`**: Estructura el plan de ejecución temporal (etapas) del proyecto.
*   **`Observation`**: Registra los informes de corrección emitidos por el Consejo Directivo.

---

## ⚙️ Integración con Bonita BPM

La comunicación directa con el motor de procesos distribuidos se realiza mediante el cliente personalizado [BonitaClient](https://github.com/EzequielReale/DSSD-2025/blob/main/integrations/bonita_client.py). Sus principales responsabilidades son:
1.  **Autenticación y Sesión**: Manejo transparente de logins dinámicos según el rol (`SOLICITANTE`, `COLABORADORA`, `DIRECTIVO`) y adquisición/mantenimiento de tokens CSRF (`X-Bonita-API-Token`).
2.  **Gestión de Casos**: Creación de nuevas instancias de proceso con contratos de datos (`start_process` y `start_process_with_contract`).
3.  **Gestión de Tareas**: Búsqueda automatizada de tareas en estado `ready`, auto-asignación al usuario de la sesión y ejecución sincrónica/asincrónica de las mismas (`execute_bonita_task`).
4.  **Lectura/Escritura de Variables**: Obtención y actualización de variables globales de caso activos e históricos (`get_case_variable`, `set_case_var`).
5.  **Cancelación Segura**: Aborto y limpieza de casos cuando ocurren fallas transaccionales en la aplicación local (`abort_case`).

---

## 🐳 Instrucciones de Despliegue con Docker

El proyecto viene preparado para levantarse con Docker de manera automática.

### Requisitos Previos
1.  Tener instalado **Docker Desktop** y **Docker Compose**.
2.  Tener en ejecución un servidor de **Bonita BPM** accesible (por defecto se asume en `http://localhost:8080/bonita` o configurable mediante `.env`).

### Configuración del Entorno
Duplique el archivo `.env.example` y renombrelo a `.env`:
```bash
cp .env.example .env
```
Asegúrese de configurar correctamente las siguientes variables en `.env`:
- `BONITA_URL`: URL del servidor Bonita.
- `BONITA_USER_SOLICITANTE`, `BONITA_USER_COLABORADORA`, `BONITA_USER_DIRECTIVO`, `BONITA_PASS`: Credenciales de acceso a Bonita BPM.
- `BONITA_PROCESS_NAME`, `BONITA_PROCESS_VERSION`: Nombre y versión del proceso de aprobación importado en Bonita.
- `SEED_ON_START`: Establecer en `1` para precargar datos de prueba al iniciar.

### Levantar la Aplicación
Ejecute el siguiente comando para construir la imagen y encender los servicios (Base de Datos PostgreSQL + Aplicación Web Django):
```bash
docker-compose up --build
```

El script de entrada (`entrypoint.sh`) realizará automáticamente las siguientes tareas:
1.  Esperar a que PostgreSQL esté listo para recibir conexiones.
2.  Aplicar las migraciones de Django (`makemigrations` y `migrate`).
3.  Ejecutar `collectstatic` para agrupar los estáticos.
4.  Crear un superusuario de manera idempotente (si se definen las variables `DJANGO_SUPERUSER_*` en el `.env`).
5.  Cargar fixtures iniciales de proyectos y necesidades si `SEED_ON_START=1`.
6.  Iniciar el servidor web en `http://localhost:8000/`.
