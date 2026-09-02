const path = require('path');
const eng = path.join(__dirname, '宁德时代', '业务', '换电', '财务模型', 'engine');
process.chdir(eng);
require(path.join(eng, 'test_verify.js'));
