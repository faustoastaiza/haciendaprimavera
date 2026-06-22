#!/bin/bash
cd "$(dirname "$0")"
PORT=8765
URL="http://localhost:$PORT"
clear
echo ""
echo "============================================="
echo "   HACIENDA PRIMAVERA - PREVISUALIZACION"
echo ""
echo "   Abriendo en: $URL"
echo "   (Cierra esta ventana para detener)"
echo "============================================="
echo ""
sleep 1
open "$URL"
if command -v npx >/dev/null 2>&1; then
  npx --yes serve -l $PORT . 2>&1
elif command -v python3 >/dev/null 2>&1; then
  python3 -m http.server $PORT
else
  echo ""
  echo "ERROR: No se encontro Node (npx) ni Python."
  echo "Instala uno con: brew install python  o  brew install node"
  read -p "Presiona Enter para cerrar..."
fi
