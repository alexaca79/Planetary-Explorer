const fs = require('fs');
const path = require('path');

const projectRoot = path.resolve(__dirname, '..');
const deploymentRoot = path.join(projectRoot, 'deployment');
const outputRoot = path.join(projectRoot, 'dist');

fs.copyFileSync(
  path.join(deploymentRoot, 'server.cjs'),
  path.join(outputRoot, 'server.js'),
);
fs.copyFileSync(
  path.join(deploymentRoot, 'package.json'),
  path.join(outputRoot, 'package.json'),
);

console.log('Prepared dependency-free App Service host.');