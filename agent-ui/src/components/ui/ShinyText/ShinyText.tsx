// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
// Portions Copyright 2026 Simon Ugorji. All Rights Reserved.
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

import './ShinyText.css';

interface ShinyTextProps {
  text: string;
  disabled?: boolean;
  speed?: number;
  className?: string;
  /** Ink the sweep passes through. Accepts `currentColor` to keep the caller's text colour. */
  color?: string;
  /** Colour of the highlight. `transparent` lets the surface show through the sweep. */
  shineColor?: string;
}

const ShinyText: React.FC<ShinyTextProps> = ({
  text,
  disabled = false,
  speed = 3,
  className = '',
  color,
  shineColor,
}) => {
  const style = {
    animationDuration: `${speed}s`,
    ...(color ? { '--shiny-color': color } : null),
    ...(shineColor ? { '--shiny-shine': shineColor } : null),
  } as React.CSSProperties;

  return (
    <div
      className={`shiny-text ${disabled ? 'disabled' : ''} ${className}`}
      style={style}
    >
      {text}
    </div>
  );
};

export default ShinyText;
