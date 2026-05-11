const sqlite3 = require('sqlite3');
const dbs = [
    'C:/Users/Usuario/Downloads/milpa/milpa_ai_backend/data/milpa.db',
    'C:/Users/Usuario/Downloads/milpa/milpa_ai_backend/data/main.db'
];

dbs.forEach(dbPath => {
    const db = new sqlite3.Database(dbPath, sqlite3.OPEN_READONLY, (err) => {
        if (err) {
            console.error('--- ERROR: ' + err.message);
            return;
        }
        console.log('--- Database: ' + dbPath + ' ---');
        db.all("SELECT name FROM sqlite_master WHERE type=\'table\'", (err, tables) => {
            if (err) return;
            const tableNames = tables.map(t => t.name);
            console.log('Tables: ' + tableNames.join(', '));
            const relevantList = ['sensor', 'reading', 'lectura', 'cultivo', 'crop', 'soil', 'edafologia', 'user', 'usuario'];
            const monitoringTables = tableNames.filter(t => relevantList.some(key => t.toLowerCase().includes(key)));

            monitoringTables.forEach(table => {
                db.get("SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=\'" + table + "\'", (err, schema) => {
                    console.log('\\nSchema for ' + table + ':\\n' + schema.sql);
                    db.get("SELECT COUNT(*) as count FROM " + table, (err, row) => {
                        console.log('Count: ' + row.count);
                    });
                });
            });
        });
    });
});
