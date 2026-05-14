from django.db import migrations

LEFT_TEXT = """Este formulario lo deben utilizar las personas naturales y jurídicas que ejerzan directa o indirectamente actividades permanentes u ocasionales en la jurisdicción del Municipio de Ciudad Bolívar, Antioquia, en cumplimiento de la Ley 14 de 1983, Decreto Ley 1333 de 1986 y el Acuerdo Municipal vigente.

El formulario debe ser presentado ante el Área Administrativa de Impuestos de la Alcaldía Municipal de Ciudad Bolívar, Calle 49 # 51-20, en las fechas del Calendario Tributario.

Todas las casillas de valores deben aproximarse al múltiplo de mil (1000) más cercano. Si no hay valor, escriba cero (0).

## MUNICIPIO O DISTRITO
Escriba CIUDAD BOLÍVAR, municipio ante quien presenta esta declaración.

## DEPARTAMENTO
Escriba ANTIOQUIA.

## FECHA MÁXIMA DE PRESENTACIÓN
Consulte el decreto municipal con el Calendario Tributario del Municipio de Ciudad Bolívar.

## AÑO GRAVABLE
El período gravable es el año calendario inmediatamente anterior al de presentación.

## DECLARACIÓN INICIAL
Marque si es la primera declaración por este período gravable.

## CORRECCIÓN
Si corrige una declaración anterior, escriba el número, día, mes y año de la declaración que corrige.

### A. INFORMACIÓN DEL CONTRIBUYENTE

## 1. NOMBRES Y APELLIDOS O RAZÓN SOCIAL
Escriba los datos tal como figuran en el documento de identificación, R.U.T. o certificado de Cámara de Comercio. Si es PERSONA NATURAL, escriba nombres y apellidos completos. Si es PERSONA JURÍDICA, escriba la razón social completa.

## 2. TIPO DE DOCUMENTO
Marque con "X" el recuadro y escriba el número de C.C., Nit. o Tarjeta de Identidad. Para el NIT, el dígito de verificación va separado con guion.

## 3. DIRECCIÓN DE NOTIFICACIÓN
Escriba la dirección que usa para efectos tributarios, indicando municipio y departamento. – Dirección establecimiento: escriba la dirección de establecimientos, agencias o sucursales en Ciudad Bolívar.

## 4. TELÉFONO
Escriba el número de teléfono de contacto.

## 5. CORREO ELECTRÓNICO
Escriba la dirección electrónica de contacto.

## 6. NÚMERO DE ESTABLECIMIENTOS
Escriba el número de establecimientos comerciales, agencias, oficinas o sucursales ubicadas en Ciudad Bolívar.

## 7. CLASIFICACIÓN
Escriba si es Gran Contribuyente, Régimen Común o Simplificado según la DIAN. – Tipo de actividad económica: marque si desarrolla en Ciudad Bolívar una actividad en forma permanente u ocasional.

### B. BASE GRAVABLE

## 8. TOTAL INGRESOS ORDINARIOS Y EXTRAORDINARIOS DEL PERÍODO EN TODO EL PAÍS
Registre la totalidad de ingresos obtenidos en todo el país durante el período gravable, incluyendo rendimientos financieros y comisiones.

## 9. MENOS INGRESOS FUERA DE ESTE MUNICIPIO
Registre el total de ingresos obtenidos fuera del municipio de Ciudad Bolívar.

## 10. TOTAL INGRESOS EN ESTE MUNICIPIO (RENGLÓN 8 MENOS 9)
Resultado de restar los ingresos fuera del municipio al total del país.

## 11. MENOS DEVOLUCIONES, REBAJAS Y DESCUENTOS
Valor de ingresos por devoluciones, rebajas o descuentos registrados en Ciudad Bolívar del año anterior.

## 12. MENOS INGRESOS POR EXPORTACIONES
Valor de exportaciones realizadas en el año inmediatamente anterior.

## 13. MENOS VENTA DE ACTIVOS FIJOS
Valor de venta de activos fijos en el año inmediatamente anterior.

## 14. MENOS ACTIVIDADES EXCLUIDAS, NO SUJETAS Y OTROS INGRESOS NO GRAVADOS
Valor de ingresos por actividades excluidas, no sujetas u otros no gravados según las normas del impuesto de industria y comercio.

## 15. MENOS ACTIVIDADES EXENTAS EN ESTE MUNICIPIO
Valor de ingresos de actividades con tratamiento de exención concedido por el Concejo Municipal de Ciudad Bolívar.

## 16. TOTAL INGRESOS GRAVABLES (RENGLÓN 10 MENOS 11, 12, 13, 14 Y 15)
Resultado de restar al total de ingresos en el municipio los conceptos deducibles de los renglones 11 a 15."""

RIGHT_TEXT = """### C. DISCRIMINACIÓN DE ACTIVIDADES GRAVADAS

Según las actividades que realice como PERSONA NATURAL o JURÍDICA en Ciudad Bolívar, registre para cada una la información requerida, iniciando con la actividad principal.

Consulte el código y tarifa de cada actividad en el Estatuto Tributario Municipal vigente de Ciudad Bolívar.

Escriba en la columna "IMPUESTO" el valor que resulte de multiplicar los ingresos gravados por la tarifa. Ejemplo: $10.000.000 x 8 ÷ 1000 = $80.000.

## TOTAL INGRESOS GRAVADOS
Totalice la sumatoria de la columna "Ingresos Gravados".

## 17. TOTAL IMPUESTO
Totalice la sumatoria de la columna "IMPUESTO".

## 18. LIQUIDACIÓN – LEY 56 DE 1981
Sólo lo diligencian empresas generadoras de energía eléctrica (Art. 51, Ley 383 de 1997). Escriba en kilovatios la capacidad instalada de la generadora en el municipio.

### D. LIQUIDACIÓN PRIVADA

## 20. TOTAL IMPUESTO DE INDUSTRIA Y COMERCIO (RENGLÓN 17 + 19)
Escriba el impuesto del renglón N° 17 más el valor de la casilla N° 19.

## 21. IMPUESTO DE AVISOS Y TABLEROS (15% del renglón 20)
Si tiene avisos y tableros en Ciudad Bolívar, multiplique el renglón N° 20 por el 15%.

## 22. PAGO POR UNIDADES COMERCIALES ADICIONALES DEL SECTOR FINANCIERO
Liquidar 25 UVT por cada oficina adicional excepto la principal (Establecimientos de crédito, instituciones financieras y compañías de seguros).

## 23. SOBRETASA BOMBERIL
No aplica para el Municipio de Ciudad Bolívar.

## 24. SOBRETASA DE SEGURIDAD
No aplica para el Municipio de Ciudad Bolívar.

## 25. TOTAL IMPUESTO A CARGO
Resultado de sumar los renglones 20 + 21 + 22 + 23 + 24.

## 26. MENOS EXENCIÓN O EXONERACIÓN SOBRE EL IMPUESTO
Si tiene derecho a disminuir el impuesto liquidado por una exención concedida, escriba el valor exento.

## 27. MENOS RETENCIONES
Valor retenido el año anterior a favor del Municipio de Ciudad Bolívar, anexando los certificados de retención.

## 28. MENOS AUTORRETENCIONES
No aplica para el Municipio de Ciudad Bolívar.

## 29. MENOS ANTICIPO LIQUIDADO EN EL AÑO ANTERIOR
Sólo aplica a contribuyentes nuevos inscritos en el R.I.T. en el año inmediatamente anterior.

## 30. ANTICIPO PARA EL AÑO SIGUIENTE
No aplica para el Municipio de Ciudad Bolívar.

## 31. SANCIONES
Valor de sanciones tributarias a liquidar con esta declaración (Arts. 192 a 198 del Estatuto Tributario Municipal).

## 32. MENOS SALDO A FAVOR DEL PERIODO ANTERIOR
Escriba el saldo a favor con los anexos que acrediten su determinación.

## 33. TOTAL SALDO A CARGO
Resultado: renglón 25 - 26 - 27 - 28 - 29 + 30 + 31 - 32.

## 34. TOTAL SALDO A FAVOR
Si el resultado del renglón 25 - 26 - 27 - 28 - 29 + 30 + 31 - 32 es menor a cero.

### E. PAGO

## 35. VALOR A PAGAR
Escriba el valor que va a pagar durante la vigencia fiscal declarada. Si no va a pagar, escriba cero.

## 36. DESCUENTO POR PRONTO PAGO
No aplica para la declaración privada de Ciudad Bolívar.

## 37. INTERESES DE MORA
No aplica para la declaración privada de Ciudad Bolívar.

## 38. TOTAL A PAGAR
Escriba el resultado del renglón N° 35.

### SELECCIÓN PAGO VOLUNTARIO

Este recuadro no aplica para la Declaración que se presenta en el Municipio de Ciudad Bolívar (Antioquia).

### F. FIRMAS

## FIRMA DEL DECLARANTE
Esta declaración debe ser firmada por quien deba cumplir el deber formal de declarar.

## FIRMA DEL CONTADOR O REVISOR FISCAL
Diligencie si existe la obligación ante el Municipio de Ciudad Bolívar."""


def update_instructivo(apps, schema_editor):
    ConfiguracionPDF = apps.get_model('tasks', 'ConfiguracionPDF')
    for cfg in ConfiguracionPDF.objects.all():
        if '### ' not in (cfg.instructivo_ica_col_izquierda or ''):
            cfg.instructivo_ica_col_izquierda = LEFT_TEXT
        if '### ' not in (cfg.instructivo_ica_col_derecha or ''):
            cfg.instructivo_ica_col_derecha = RIGHT_TEXT
        cfg.save()


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0021_add_instructivo_ica_cols'),
    ]

    operations = [
        migrations.RunPython(update_instructivo, migrations.RunPython.noop),
    ]
