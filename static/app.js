const $ = id => document.getElementById(id);
let lastVisualPrompt = "";
let previewMode = "post";

function showMessage(text, error=false){
  $("message").textContent = text;
  $("message").className = error ? "error" : "success";
}

async function refreshStatus(){
  try{
    const x = await (await fetch("/api/status")).json();
    $("aiStatus").textContent = x.ai_enabled ? `OpenAI · ${x.ai_model}` : "OpenAI not configured";
    $("aiDetail").textContent = x.image_enabled ? `Image: ${x.image_model}` : "Add OPENAI_API_KEY";
    $("metaStatus").textContent = x.instagram_connected ? `Instagram · @${x.instagram_username}` : "Instagram not connected";
    $("connectionPill").textContent = x.instagram_connected ? `● @${x.instagram_username}` : "○ Not connected";
    $("connectionPill").className = "pill " + (x.instagram_connected ? "connected" : "muted");
    if(x.instagram_username) $("previewUsername").textContent = x.instagram_username;
    if(x.public_base_url_configured){
      $("mediaStatus").textContent = "✓ Public HTTPS publishing is enabled.";
    }else{
      $("mediaStatus").textContent = "⚠ Add PUBLIC_BASE_URL (your ngrok HTTPS URL) to enable publishing.";
    }
  }catch(e){ $("aiStatus").textContent = "Status unavailable"; }
}

async function generateIdeas(){
  const f = new FormData();
  ["niche","goal","audience"].forEach(k=>f.append(k,$(k).value));
  f.append("language","English");
  $("ideaList").innerHTML = "<div class='loading'>Creating ideas…</div>";
  try{
    const x = await (await fetch("/api/ideas",{method:"POST",body:f})).json();
    if(!x.ideas){ $("ideaList").innerHTML=`<div class='error'>${escapeHtml(x.error||"Could not generate ideas")}</div>`; return; }
    $("ideaList").innerHTML=x.ideas.map((idea,i)=>`<button class="idea" onclick='selectIdea(${JSON.stringify(idea)})'><span>${String(i+1).padStart(2,"0")}</span><b>${escapeHtml(idea)}</b><i>→</i></button>`).join("");
  }catch(e){ $("ideaList").innerHTML=`<div class='error'>${escapeHtml(e.message)}</div>`; }
}

function selectIdea(value){ $("idea").value=value; generateContent(); }

async function generateContent(){
  if(!$('idea').value.trim()){ showMessage("Choose an idea first.",true); return; }
  const f=new FormData();
  ["idea","niche","goal","audience","tone"].forEach(k=>f.append(k,$(k).value));
  f.append("language","English"); f.append("content_type",$("contentType").value);
  showMessage("AI is writing the content…");
  try{
    const r=await fetch("/api/generate",{method:"POST",body:f}); const x=await r.json();
    if(!r.ok||!x.data){showMessage(x.error||"Generation failed",true);return;}
    const d=x.data;
    $("hook").value=d.hook||""; $("caption").value=d.caption||""; $("cta").value=d.cta||"";
    $("hashtags").value=Array.isArray(d.hashtags)?d.hashtags.join(" "):(d.hashtags||"");
    lastVisualPrompt=d.visual_direction||"";
    $("visualDirection").textContent=lastVisualPrompt||"A polished Instagram visual matched to your content.";
    $("visualTitle").textContent=d.hook||$("idea").value;
    updatePreview();
    showMessage("Content generated. Now create the visual.");
  }catch(e){showMessage(e.message,true);}
}

async function uploadMedia(){
  const input = $("mediaFile");
  if(!input.files || !input.files[0]){
    showMessage("Choose a JPG, PNG, or WEBP image first.", true);
    return;
  }

  const f = new FormData();
  f.append("media", input.files[0]);

  $("mediaStatus").textContent = "Uploading image…";
  showMessage("Uploading your image and preparing it for Instagram…");

  try{
    const r = await fetch("/api/upload-media", {method:"POST", body:f});
    const x = await r.json();

    if(!r.ok || !x.ok){
      $("mediaStatus").textContent = "Upload failed.";
      showMessage(x.error || "Image upload failed.", true);
      return;
    }

    setGeneratedImage(x.image_url);
    $("mediaUrl").value = x.public_url || x.image_url;

    if(x.public_url){
      $("mediaStatus").innerHTML = "✓ Image ready for Instagram publishing.";
      showMessage("Image uploaded. The public HTTPS media URL was created automatically.");
    }else{
      $("mediaStatus").innerHTML = "✓ Image uploaded for preview. Configure PUBLIC_BASE_URL to publish.";
      showMessage("Image uploaded for preview. Add PUBLIC_BASE_URL to enable Instagram publishing.", true);
    }
  }catch(e){
    $("mediaStatus").textContent = "Upload failed.";
    showMessage(e.message, true);
  }
}

async function generateVisual(){
  if(!$('idea').value.trim()){showMessage("Generate content first.",true);return;}
  const f=new FormData();
  f.append("idea",$("idea").value); f.append("niche",$("niche").value); f.append("tone",$("tone").value); f.append("prompt",lastVisualPrompt);
  showMessage("Creating your AI visual…");
  $("imagePlaceholder").innerHTML="<span class='spinner'></span><b>Generating…</b><small>This can take a moment</small>";
  $("generatedImage").hidden=true;
  try{
    const r=await fetch("/api/generate-image",{method:"POST",body:f}); const x=await r.json();
    if(!r.ok||!x.ok){showMessage(x.error||"Image generation failed",true);resetImagePlaceholder();return;}
    setGeneratedImage(x.image_url);
    if(x.public_url) $("mediaUrl").value = x.public_url;
    $("mediaStatus").textContent = x.public_url
      ? "✓ AI visual is ready for Instagram publishing."
      : "⚠ AI visual ready for preview; configure PUBLIC_BASE_URL to publish.";
    showMessage(x.public_url ? "Visual generated. Public media URL is ready for publishing." : "Visual generated for preview. Configure PUBLIC_BASE_URL to publish.");
  }catch(e){showMessage(e.message,true);resetImagePlaceholder();}
}
function regenerateVisual(){ generateVisual(); }
function setGeneratedImage(url){
  $("generatedImage").src=url+"?t="+Date.now(); $("generatedImage").hidden=false; $("imagePlaceholder").hidden=true;
  $("previewImage").src=url+"?t="+Date.now(); $("previewImage").style.display="block"; $("previewFallback").style.display="none";
}
function resetImagePlaceholder(){ $("imagePlaceholder").hidden=false; $("imagePlaceholder").innerHTML="<span>✦</span><b>AI visual</b><small>1024 × 1024</small>"; }

function updatePreview(){
  const caption=$("caption").value.trim();
  $("previewCaption").textContent=caption||"Your caption will appear here.";
  $("previewTags").textContent=$("hashtags").value.trim()||"#yourbrand #content";
  $("previewHook").textContent=$("hook").value||$("idea").value||"Your AI visual";
  $("reelPreviewText").textContent=$("hook").value||$("idea").value||"Your Reel script will appear here.";
}
function togglePreviewMode(mode){
  previewMode=mode; $("phone").classList.toggle("reel-mode",mode==="reel"); $("reelOverlay").style.display=mode==="reel"?"flex":"none";
}
function approveDraft(){
  if(!$("idea").value||!$("caption").value){showMessage("Generate content before approving.",true);return;}
  const f=new FormData(); ["idea","niche","goal","caption","hashtags"].forEach(k=>f.append(k,$(k).value));
  f.append("media",$("previewImage").src||"");
  fetch("/api/save",{method:"POST",body:f}).then(r=>r.json()).then(x=>{
    if(x.ok){$("publishBtn").disabled=false;$("approvalIcon").textContent="✓";$("approvalText").textContent="Draft approved";$("approvalSub").textContent="Publishing is now unlocked.";showMessage("Draft approved. Publishing is unlocked.");}
    else showMessage("Could not save draft.",true);
  });
}
async function publishToInstagram(){
  const mediaUrl=$("mediaUrl").value.trim();
  if(!mediaUrl){showMessage("Upload or generate an image before publishing.",true);return;}
  const f=new FormData();
  f.append("media_url",mediaUrl);
  f.append("caption",($("caption").value+"\n\n"+$("hashtags").value).trim());
  showMessage("Sending the approved post to Instagram…");
  try{const x=await (await fetch("/api/publish",{method:"POST",body:f})).json(); if(x.ok)showMessage("Published successfully to Instagram ✓"); else showMessage(x.error||"Publishing failed",true);}catch(e){showMessage(e.message,true);}
}

["caption","hashtags","hook","idea"].forEach(id=>document.addEventListener("input",e=>{if(e.target.id===id)updatePreview();}));
function escapeHtml(s){return String(s).replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[m]));}
updatePreview(); refreshStatus(); togglePreviewMode("post");
