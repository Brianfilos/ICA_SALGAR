from django.db import models

class Departamento(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre

class Municipio(models.Model):
    departamento = models.ForeignKey(Departamento, on_delete=models.PROTECT, related_name="municipios")
    nombre = models.CharField(max_length=120)
    activo = models.BooleanField(default=True)

    class Meta:
        unique_together = ("departamento", "nombre")

    def __str__(self):
        return self.nombre

    
class ActividadEconomica(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=255)

    # tarifa oculta para cálculo (la defines tú en admin)
    tarifa = models.DecimalField(max_digits=10, decimal_places=6)

    tipo = models.CharField(
        max_length=15,
        choices=[
            ("INDUSTRIAL", "Industrial"),
            ("COMERCIAL", "Comercial"),
            ("SERVICIO", "Servicio"),
        ],
    )

    activo = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

