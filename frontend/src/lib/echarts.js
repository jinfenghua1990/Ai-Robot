/**
 * ECharts 按需加载配置
 * 只导入项目实际使用的模块，减少 bundle 体积
 */
import * as echarts from 'echarts/core';
import { BarChart, SankeyChart, GraphChart, PieChart, RadarChart, LineChart, EffectScatterChart, ScatterChart, CandlestickChart } from 'echarts/charts';
import {
  GridComponent, TooltipComponent, LegendComponent, TitleComponent,
  VisualMapComponent, DataZoomComponent, GraphicComponent,
  MarkLineComponent, MarkPointComponent, ToolboxComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  // 图表类型
  BarChart, SankeyChart, GraphChart, PieChart, RadarChart, LineChart,
  EffectScatterChart, ScatterChart, CandlestickChart,
  // 组件
  GridComponent, TooltipComponent, LegendComponent, TitleComponent,
  VisualMapComponent, DataZoomComponent, GraphicComponent,
  MarkLineComponent, MarkPointComponent, ToolboxComponent,
  // 渲染器
  CanvasRenderer,
]);

export default echarts;
