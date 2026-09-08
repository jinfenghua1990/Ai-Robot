import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';

export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.node },
      parserOptions: { ecmaFeatures: { jsx: true }, sourceType: 'module' },
    },
    plugins: { 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      ...js.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      // Vite Fast Refresh can safely retain primitive/object constant exports.
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-undef': 'error',
      'no-empty': ['error', { allowEmptyCatch: true }],
      'no-console': 'off',
      // React 18 未启用 React Compiler；保留提示，但不让编译器专属建议阻断检查
      'react-hooks/static-components': 'warn',
      // set-state-in-effect 是性能建议，关闭避免噪音
      'react-hooks/set-state-in-effect': 'off',
      // 允许 .map 索引 key（数据稳定时不算 anti-pattern）
      'react/no-array-index-key': 'off',
    },
  },
];
