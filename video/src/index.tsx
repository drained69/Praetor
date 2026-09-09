import { registerRoot } from "remotion";
import { Composition } from "remotion";
import { PraetorDemo } from "./PraetorDemo";

registerRoot(() => (
  <Composition id="PraetorDemo" component={PraetorDemo} durationInFrames={2220} fps={30} width={1920} height={1080} />
));
