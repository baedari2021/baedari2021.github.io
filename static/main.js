(function(){
  // 모바일 메뉴
  var b=document.querySelector('.menu-btn'),n=document.getElementById('gnb');
  if(b&&n){b.addEventListener('click',function(){var o=n.classList.toggle('open');b.setAttribute('aria-expanded',o);});}
  // 소식 분류 필터
  var chips=document.querySelectorAll('.chip'),list=document.getElementById('newslist');
  chips.forEach(function(c){c.addEventListener('click',function(){
    chips.forEach(function(x){x.classList.remove('on')});c.classList.add('on');
    var cat=c.dataset.cat;
    list.querySelectorAll('li').forEach(function(li){li.hidden=!!cat&&li.dataset.cat!==cat;});
  });});
  // 문의 폼: 전송 주소가 있으면 서버(관리페이지)로, 없으면 메일 작성 창으로
  var f=document.getElementById('inquiry');
  if(f){f.addEventListener('submit',function(e){
    e.preventDefault();
    var d=new FormData(f),st=f.querySelector('.status'),ep=f.dataset.endpoint;
    var data={type:d.get('type'),name:d.get('name'),contact:d.get('contact'),message:d.get('message'),website:d.get('website'),source:location.search||document.referrer||'direct'};
    if(ep){
      st.textContent='보내는 중…';
      fetch(ep,{method:'POST',headers:{'Content-Type':'text/plain;charset=utf-8'},body:JSON.stringify(data)})
        .then(function(r){return r.json()}).then(function(j){
          if(j.ok){st.textContent='문의가 접수되었습니다. 확인 후 연락드리겠습니다.';f.reset();}else{throw 0}
        }).catch(function(){st.textContent='전송에 실패했습니다. 전화 또는 이메일로 문의해 주세요.';});
    }else{
      var s=encodeURIComponent('[홈페이지 문의] '+data.type),
          t=encodeURIComponent('이름·기관: '+data.name+'\n연락처: '+data.contact+'\n\n'+data.message);
      location.href='mailto:'+f.dataset.mailto+'?subject='+s+'&body='+t;
    }
  });}
})();
