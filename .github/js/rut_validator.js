define(["jquery"], function ($) {
  /**
   * Check rut using an input html element
   * Reference https://gist.github.com/rotvulpix/69a24cc199a4253d058c
   */
  return {
    checkRut: function (rut, checkType = false) {
      // Preventive check
      if (checkType) {
        var docType = $("#bIdType");
        if (docType.value !== "0") {
          // all is good in the world
          rut.setCustomValidity("");
          return;
        }
      }

      // Despejar Puntos
      var valor = rut.value.replace(".", "");
      // Despejar Guión
      valor = valor.replace("-", "");

      // Aislar Cuerpo y Dígito Verificador
      cuerpo = valor.slice(0, -1);
      dv = valor.slice(-1).toUpperCase();

      // Formatear RUN
      rut.value = cuerpo + "-" + dv;

      // Calcular Dígito Verificador
      suma = 0;
      multiplo = 2;

      if (cuerpo.length < 1) {
        rut.setCustomValidity("RUT Incompleto");
        return false;
      }

      // Para cada dígito del Cuerpo
      for (i = 1; i <= cuerpo.length; i++) {
        // Obtener su Producto con el Múltiplo Correspondiente
        index = multiplo * valor.charAt(cuerpo.length - i);

        // Sumar al Contador General
        suma = suma + index;

        // Consolidar Múltiplo dentro del rango [2,7]
        if (multiplo < 7) {
          multiplo = multiplo + 1;
        } else {
          multiplo = 2;
        }
      }

      // Calcular Dígito Verificador en base al Módulo 11
      dvEsperado = 11 - (suma % 11);

      // Casos Especiales (0 y K)
      dv = dv == "K" ? 10 : dv;
      dv = dv == 0 ? 11 : dv;

      // Validar que el Cuerpo coincide con su Dígito Verificador
      if (dvEsperado != dv) {
        rut.setCustomValidity("RUT Inválido");
        return false;
      }

      // Si todo sale bien, eliminar errores (decretar que es válido)
      rut.setCustomValidity("");
    },
  };
});
