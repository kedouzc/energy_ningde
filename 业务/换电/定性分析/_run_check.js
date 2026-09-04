const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const script = 'd:\\AI\\证券投资\\投研\\能源\\宁德时代\\业务\\换电\\定性分析\\重卡与城配物流换电规模测算_合并对比.py';
const outDir = 'd:\\AI\\证券投资\\投研\\能源\\宁德时代\\业务\\换电\\定性分析';

const out = execFileSync('python', [script], { encoding: 'utf-8', maxBuffer: 1024*1024*64 });
fs.writeFileSync(path.join(outDir, '_check_out.txt'), out, 'utf-8');
console.log('WROTE', path.join(outDir, '_check_out.txt'), 'len=', out.length);
