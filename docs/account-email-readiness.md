# MECORRESPONDE — verificación de email y recuperación de cuenta

El código de verificación y recuperación está diseñado para permanecer inactivo hasta que exista un proveedor transaccional autorizado y probado. Este documento no activa ningún servicio ni implica gasto.

## Flujo construido

- Tokens aleatorios de un solo uso para `VERIFY_EMAIL` y `PASSWORD_RESET`.
- Solo se guarda SHA-256 del token; el valor utilizable no se persiste en claro.
- Verificación: caducidad de 24 horas.
- Recuperación de contraseña: caducidad de 30 minutos.
- Pedir un token nuevo invalida los anteriores del mismo tipo.
- Los enlaces llevan el token en el fragmento `#...`, que el navegador no envía en la petición HTTP inicial; la confirmación se hace después mediante POST.
- Cambiar la contraseña revoca todas las sesiones abiertas.
- La solicitud de recuperación devuelve una respuesta genérica para no confirmar si un email tiene cuenta.
- La reclamación de un expediente por una cuenta solo exigirá email verificado cuando la verificación esté explícitamente activada y la entrega transaccional haya sido comprobada.

## Entrega transaccional

Se ha implementado un adaptador para la API HTTPS de Brevo (`POST https://api.brevo.com/v3/smtp/email`) porque evita depender de SMTP desde la infraestructura web. La documentación oficial consultada exige una API key y un remitente configurado/verificado:

- https://developers.brevo.com/docs/send-a-transactional-email
- https://developers.brevo.com/reference/send-transac-email

La aplicación mantiene el proveedor desactivado por defecto. Para considerarlo operativo deben existir, en variables de entorno, proveedor, API key, remitente y URL HTTPS de acciones; además `TRANSACTIONAL_EMAIL_VERIFIED` debe mantenerse en `False` hasta que una prueba real de entrega haya funcionado.

## Activación pendiente

No crear cuenta, remitente, dominio, API key ni plan externo de forma automática. Cuando MECORRESPONDE esté preparado para desbloquear beta pública habrá que:

1. revisar proveedor, condiciones, DPA/ubicación de datos y coste vigentes;
2. obtener aprobación antes de cualquier alta que implique facturación o datos reales;
3. configurar un remitente de MECORRESPONDE;
4. probar verificación y recuperación de extremo a extremo;
5. solo entonces marcar la entrega como verificada y activar la obligatoriedad de verificación.
