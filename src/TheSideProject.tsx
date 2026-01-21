import { useEffect, useRef, useState, useCallback, useLayoutEffect } from 'react';

// Use your direct Space URL here. 
// For Hugging Face Spaces, the direct API URL is usually:
// https://{username}-{space-name}.hf.space
// e.g. https://grmd-thesideproject-qwen3-0-6b.hf.space
// Make sure to remove the trailing slash.
const API_URL = "http://100.123.161.83:7860"; 

export default function TheSideProject() {
  const [text, setText] = useState<string>("");
  const [temp, setTemp] = useState<number>(1.0);
  const [context, setContext] = useState<number>(10);
  
  // Refs for state
  const abortControllerRef = useRef<AbortController | null>(null);
  const latestParamsRef = useRef({ temp: 1.0, context: 10 });
  const isRunningRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null); // Container for text
  const containerRef = useRef<HTMLDivElement>(null); // Scrollable area

  // Initialize connection once
  useEffect(() => {
    // Start initial stream
    startStream(true);

    // Global click/keypress listener for restart
    const handleInteraction = () => {
       // Restart with reset=true
       startStream(true);
    };

    window.addEventListener('mousedown', handleInteraction);
    //window.addEventListener('keydown', handleInteraction);

    return () => {
      window.removeEventListener('mousedown', handleInteraction);
      //window.removeEventListener('keydown', handleInteraction);
      
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const startStream = async (reset: boolean = false) => {
    // If resetting or re-connecting, abort previous fetch
    if (abortControllerRef.current) {
        abortControllerRef.current.abort();
    }
    
    const controller = new AbortController();
    abortControllerRef.current = controller;

    isRunningRef.current = true;
    
    try {
      const { temp, context } = latestParamsRef.current;
      
      // Prepare payload
      const payload = {
          temp: temp,
          context: context
          // Removed: reset, state_ids. Every call is a new stream.
      };

      const response = await fetch(`${API_URL}/generate`, {
          method: 'POST',
          headers: {
              'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
          signal: controller.signal
      });

      if (!response.ok || !response.body) {
          throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      
      while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          
          const chunk = decoder.decode(value, { stream: true });
          // NDJSON parsing (New-line Delimited JSON)
          const lines = chunk.split('\n').filter(line => line.trim() !== '');
          
          for (const line of lines) {
              try {
                  const data = JSON.parse(line);
                  // Expecting data = { text: "...", count: ... }
                  if (data.text) {
                      // If this is the very first chunk after a reset request
                      if (reset) {
                          setText(data.text);
                          reset = false;
                      } else {
                          // Append only new content. 
                          setText(prev => prev + data.text);
                      }
                  }
              } catch (e) {
                  console.warn("JSON parse error", e);
              }
          }
      }
      
    } catch (error: any) {
      if (error.name === 'AbortError') {
          console.log('Fetch aborted');
          return;
      }
      console.error("Stream error:", error);
      
      // Simple retry logic if connection drops unexpectedly
      // Commented out automatic retry to prevent loops
      // setTimeout(() => {
      //     if (isRunningRef.current) startStream(false); 
      // }, 2000);
    } finally {
      if (abortControllerRef.current === controller) {
          isRunningRef.current = false;
      }
    }
  };

  // Handle mouse movement - ONLY updates params, NO restart logic
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const { clientX, clientY } = e;
    const { innerWidth, innerHeight } = window;

    // Calculate Context (5-128) based on X (Left -> Right)
    // Previous 1-20 was too small for coherent text
    const rawCtx = (clientX / innerWidth) * 24 + 1;
    const newCtx = Math.round(Math.max(1, Math.min(25, rawCtx)));

    // Calculate Temp (0-2) based on Y (Top -> Bottom is High -> Low?)
    // User said: "Top temp higher, Bottom temp lower" => Y=0 -> Temp=2.0
    const rawTemp = ((innerHeight - clientY) / innerHeight) * 2;
    const newTemp = parseFloat(Math.max(0.7, Math.min(2, rawTemp)).toFixed(2));

    // Update UI state immediately
    setTemp(newTemp);
    setContext(newCtx);
    
    // Update ref for the streamer to pick up on NEXT restart
    latestParamsRef.current = { temp: newTemp, context: newCtx };
  }, []);

  // Handle touch movement for mobile
  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    const touch = e.touches[0];
    const { clientX, clientY } = touch;
    const { innerWidth, innerHeight } = window;

    const rawCtx = (clientX / innerWidth) * 24 + 1;
    const newCtx = Math.round(Math.max(1, Math.min(25, rawCtx)));

    const rawTemp = ((innerHeight - clientY) / innerHeight) * 2;
    const newTemp = parseFloat(Math.max(0.7, Math.min(2, rawTemp)).toFixed(2));

    setTemp(newTemp);
    setContext(newCtx);
    latestParamsRef.current = { temp: newTemp, context: newCtx };
  }, []);

  // Check for overflow and reset if full
  useLayoutEffect(() => {
    if (containerRef.current && contentRef.current) {
      // If content height > container height, it's full
      if (contentRef.current.clientHeight > containerRef.current.clientHeight) {
         // Use a small timeout to prevent render-loop
         const timer = setTimeout(() => {
             startStream(true);
         }, 100);
         return () => clearTimeout(timer);
      }
    }
    // Also scroll to bottom if not resetting
    bottomRef.current?.scrollIntoView({ behavior: "auto" });
  }, [text]);

  return (
    <>
    <style>{`
      .font-terminal-override, .font-terminal-override * {
        font-family: "Menlo", "Monaco", "Consolas", "Liberation Mono", "Lucida Console", monospace !important;
      }
    `}</style>
    <div 
      className="fixed inset-0 w-full h-full bg-black text-black overflow-hidden cursor-crosshair flex items-center justify-center z-50 touch-none font-terminal-override"
      onMouseMove={handleMouseMove}
      onTouchMove={handleTouchMove}
    >
      {/* Centered Canvas Container - Responsive */}
      <div className="w-full h-full md:w-[1000px] md:h-[1000px] md:max-w-[95vw] md:max-h-[95vh] border-0 md:border border-black bg-white flex flex-col relative shadow-none md:shadow-sm select-none pointer-events-none transition-all duration-300">
        
        {/* Text Content Area - No Scrollbar, Hidden Overflow */}
        <div 
          ref={containerRef}
          className="flex-grow whitespace-pre-wrap text-xs md:text-sm font-bold leading-none tracking-tighter break-all overflow-hidden relative p-4 md:p-6 [&::-webkit-scrollbar]:hidden [scrollbar-width:none]"
          style={{ 
             lineHeight: '1.1em',
             letterSpacing: '-0.05em'
          }}
        >
           <div ref={contentRef}>
              {/* Floated QR Code - Top Right, Tight Wrapping ("Missing Corner" Effect), Pure Square */}
              <div className="float-right pointer-events-none mix-blend-multiply -mr-4 -mt-4 md:-mr-6 md:-mt-6 ml-4 mb-4 md:ml-6 md:mb-6">
                 <img src="/cm_qr.svg" alt="QR Code" className="w-24 h-24 md:w-32 md:h-32 block" />
              </div>

              {text}
              <div ref={bottomRef} />
           </div>
        </div>

        {/* Minimal Info Overlay - Bottom Right */}
        <div 
           className="absolute bottom-4 right-4 md:bottom-6 md:right-6 text-[10px] md:text-xs text-right font-bold opacity-60 flex flex-col-reverse gap-1 tracking-tighter pointer-events-none"
        >
           <div className="uppercase">The Side Project / Model: Qwen3_0.6B</div>
           <div className="mt-2">CTX: {context}</div>
           <div>TMP: {temp.toFixed(2)}</div>
        </div>
      </div>
    </div>
    </>
  );
}
