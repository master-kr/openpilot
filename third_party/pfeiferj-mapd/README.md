# MAPD implementation by pfeiferj
https://github.com/pfeiferj/openpilot-mapd/releases/

The bundled mapd downloads requested offline map archives from
`https://map-data.pfeifer.dev/`. The archive selection is sent through the
`OSMDownloadLocations` shared-memory Param; this branch always requests `KR`
(South Korea). The underlying road data is from OpenStreetMap.
