import time
import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.conf import settings
from projects.models import Project, ProjectStatus, Observation
from integrations.bonita_client import BonitaClient

class Command(BaseCommand):
    help = 'Seeds the database and Bonita with test data for reports'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting data seeding...'))

        # 1. Create Users
        solicitante = self._create_user('solicitante', 'password123', 'ONG Solicitante')
        directivo = self._create_user('directivo', 'password123', 'Consejo Directivo')
        
        # Bonita Clients
        client_solicitante = BonitaClient(role="SOLICITANTE")
        client_directivo = BonitaClient(role="DIRECTIVO")

        # 2. Seed Lifecycle Metrics (Completed Projects)
        self.stdout.write("Seeding Lifecycle Metrics data...")
        for i in range(3):
            self._create_completed_project(i, solicitante, client_solicitante, client_directivo)

        # 3. Seed Compliance Report (Resolved Observations)
        self.stdout.write("Seeding Compliance Report data...")
        self._create_project_with_observation(solicitante, client_solicitante, client_directivo, delayed=False)
        self._create_project_with_observation(solicitante, client_solicitante, client_directivo, delayed=True)

        # 4. Seed Stalled Projects (Pending Tasks)
        self.stdout.write("Seeding Stalled Projects data...")
        self._create_stalled_project(solicitante, client_solicitante)

        self.stdout.write(self.style.SUCCESS('Seeding completed successfully!'))

    def _create_user(self, username, password, group_name):
        user, created = User.objects.get_or_create(username=username, defaults={'email': f'{username}@example.com'})
        if created:
            user.set_password(password)
            user.save()
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)
            self.stdout.write(f"Created user: {username}")
        return user

    def _create_completed_project(self, index, user, client_sol, client_dir):
        # Create Project
        project = Project.objects.create(
            name=f"Proyecto Finalizado {index+1}",
            description="Proyecto de prueba finalizado",
            start_date=timezone.now().date() - timedelta(days=30),
            end_date=timezone.now().date() + timedelta(days=30),
            created_by_user=user,
            status=ProjectStatus.FINISHED
        )

        # Start Bonita Process
        try:
            case_id = client_sol.start_process_with_contract(
                settings.BONITA_PROCESS_NAME,
                settings.BONITA_PROCESS_VERSION,
                {
                    "nombreProyectoInput": project.name,
                    "montoInput": 10000,
                    "emailSolicitanteInput": user.email
                }
            )
            project.bonita_case_id = case_id
            project.save()

            # Advance workflow
            # 0. "Crear proyecto en la app" (Solicitante)
            self._execute_task(client_sol, case_id, "Crear proyecto en la app", {})

            # 1. "Ejecución del proyecto" (Solicitante) - It seems "Analizar viabilidad" is skipped or auto-completed
            self._execute_task(client_sol, case_id, "Ejecución del proyecto", {})
            
            # 2. "Elaborar informe final del proyecto" (Solicitante) - To finish the case
            self._execute_task(client_sol, case_id, "Elaborar informe final del proyecto", {})
            
            self.stdout.write(f"Created completed project: {project.name} (Case {case_id})")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating completed project: {e}"))

    def _create_project_with_observation(self, user, client_sol, client_dir, delayed):
        project = Project.objects.create(
            name=f"Proyecto con Observación {'Demorada' if delayed else 'A tiempo'}",
            description="Proyecto para probar cumplimiento",
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=60),
            created_by_user=user,
            status=ProjectStatus.EXECUTING
        )

        try:
            # 1. Start Main Process
            case_id = client_sol.start_process_with_contract(
                settings.BONITA_PROCESS_NAME, settings.BONITA_PROCESS_VERSION,
                {"nombreProyectoInput": project.name, "montoInput": 5000, "emailSolicitanteInput": user.email}
            )
            project.bonita_case_id = case_id
            project.save()
            
            # Advance to Execution
            self._execute_task(client_sol, case_id, "Crear proyecto en la app", {})
            self._execute_task(client_sol, case_id, "Ejecución del proyecto", {})
            
            # 2. Start Monitoring Process
            mon_case_id = client_dir.start_process_with_contract(
                "Monitoreo", settings.BONITA_PROCESS_VERSION, {}
            )
            
            # Create Observation
            obs = Observation.objects.create(
                project=project,
                monitoring_case_id=mon_case_id,
                observer_label="directivo",
                text="Observación de prueba",
                resolved=True,
                # For delayed, we'd ideally backdate created_at, but auto_now_add makes it hard.
                # We can update it after creation.
            )
            
            if delayed:
                obs.created_at = timezone.now() - timedelta(days=10)
            else:
                obs.created_at = timezone.now() - timedelta(days=2)
            obs.save()

            # Advance Monitoring: "Revisión de proyectos" -> "Enviar informe" -> "Resolver problemas"
            payload_init = {
                "idProyectoInput": project.id,
                "aprobadoInput": False, # False triggers observation flow
                "emailConsejoInput": "directivo@example.com",
                "emailOngInput": user.email,
            }
            self._execute_task(client_dir, mon_case_id, "Revisión de proyectos", payload_init)
            
            self._execute_task(client_dir, mon_case_id, "Enviar informe de sugerencias", {})
            
            # "Resolver problemas" (Solicitante) - This completes the observation cycle
            self._execute_task(client_sol, mon_case_id, "Resolver problemas", {})
            
            self.stdout.write(f"Created observation project: {project.name}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating observation project: {e}"))

    def _create_stalled_project(self, user, client_sol):
        project = Project.objects.create(
            name="Proyecto Detenido",
            description="Proyecto con tarea pendiente",
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=90),
            created_by_user=user,
            status=ProjectStatus.OPEN
        )

        try:
            case_id = client_sol.start_process_with_contract(
                settings.BONITA_PROCESS_NAME, settings.BONITA_PROCESS_VERSION,
                {"nombreProyectoInput": project.name, "montoInput": 20000, "emailSolicitanteInput": user.email}
            )
            project.bonita_case_id = case_id
            project.save()
            
            # Advance to "Ejecución del proyecto"
            self._execute_task(client_sol, case_id, "Crear proyecto en la app", {})
            
            # Leave it at "Ejecución del proyecto" (Solicitante task)
            # Since we just created it, it's "stalled" for 0 seconds.
            # But the report logic was modified to > 3 seconds for testing, so it should show up.
            
            self.stdout.write(f"Created stalled project: {project.name}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating stalled project: {e}"))

    def _execute_task(self, client, case_id, task_name, payload):
        # Retry loop to wait for task to appear
        for _ in range(10):
            try:
                # We use execute_task_with_retry logic essentially
                tasks = client.get_active_tasks(case_id)
                target_task = next((t for t in tasks if t['displayName'] == task_name), None)
                
                if target_task:
                    client.execute_task(case_id, task_name, client.get_session_user_id(), payload)
                    return
            except Exception:
                pass
            time.sleep(1)
        
        # If we get here, we failed. Let's print what tasks WERE found to help debug.
        try:
            tasks = client.get_active_tasks(case_id)
            task_names = [t['displayName'] for t in tasks]
            print(f"Warning: Task '{task_name}' not found for case {case_id}. Available tasks: {task_names}")
        except:
            print(f"Warning: Task '{task_name}' not found for case {case_id}. Could not list available tasks.")
